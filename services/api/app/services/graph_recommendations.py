from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.config import get_settings
from app.models import DailyGoal, Product, UserAccount, UserProfile, UserRecipe

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GraphRecommendationSignal:
    option_id: str
    score: float
    reason: str


def recommend_recipe_options_with_graph(
    *,
    session: Session,
    current_user: UserAccount,
    generated_options: list[dict[str, object]],
) -> dict[str, GraphRecommendationSignal]:
    settings = get_settings()
    if (
        not settings.neo4j_enabled
        or not settings.neo4j_uri
        or not settings.neo4j_username
        or not settings.neo4j_password
    ):
        return {}
    if current_user.id is None or not generated_options:
        return {}

    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("Neo4j driver is not installed; graph recommendations disabled")
        return {}

    current_profile = session.get(UserProfile, current_user.id)
    if current_profile is None:
        return {}

    user_rows = session.exec(
        select(UserAccount, UserProfile).join(UserProfile, UserProfile.user_id == UserAccount.id)
    ).all()
    if len(user_rows) < 2:
        return {}

    recipe_rows = session.exec(
        select(UserRecipe).order_by(UserRecipe.updated_at.desc(), UserRecipe.created_at.desc())
    ).all()
    if not recipe_rows:
        return {}

    product_ids = [recipe.product_id for recipe in recipe_rows]
    products = session.exec(select(Product).where(Product.id.in_(product_ids))).all() if product_ids else []
    products_by_id = {product.id: product for product in products if product.id is not None}

    goals = session.exec(select(DailyGoal).order_by(DailyGoal.user_id, DailyGoal.date.desc())).all()
    latest_goals: dict[int, DailyGoal] = {}
    for goal in goals:
        if goal.user_id not in latest_goals:
            latest_goals[goal.user_id] = goal

    graph_users = [
        _serialize_user(user=user, profile=profile, goal=latest_goals.get(user.id or -1))
        for user, profile in user_rows
        if user.id is not None
    ]
    graph_recipes = [
        _serialize_recipe(recipe=recipe, product=products_by_id.get(recipe.product_id))
        for recipe in recipe_rows
        if recipe.id is not None
    ]
    graph_options = [_serialize_option(option) for option in generated_options]
    graph_options = [option for option in graph_options if option.get("id")]
    if not graph_options:
        return {}

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    try:
        with driver.session(database=settings.neo4j_database or None) as neo_session:
            rows = neo_session.execute_write(
                _build_and_score_graph,
                current_user_id=current_user.id,
                users=graph_users,
                recipes=graph_recipes,
                options=graph_options,
            )
    except Exception as exc:
        logger.warning("Neo4j recommendation failed: %s", exc)
        return {}
    finally:
        driver.close()

    if not rows:
        return {}

    max_score = max(float(row["raw_score"]) for row in rows)
    divisor = max(max_score, 1.0)
    signals: dict[str, GraphRecommendationSignal] = {}
    for row in rows:
        option_id = str(row["option_id"])
        signals[option_id] = GraphRecommendationSignal(
            option_id=option_id,
            score=round(float(row["raw_score"]) / divisor * 30.0, 2),
            reason=_build_reason(
                usernames=[str(item) for item in row.get("similar_usernames", []) if str(item).strip()],
                shared_tags=int(row.get("shared_tags") or 0),
                shared_ingredients=int(row.get("shared_ingredients") or 0),
            ),
        )
    return signals


def _serialize_user(*, user: UserAccount, profile: UserProfile, goal: DailyGoal | None) -> dict[str, Any]:
    return {
        "id": int(user.id),
        "username": user.username,
        "sex": profile.sex.value,
        "activity_level": profile.activity_level.value,
        "goal_type": profile.goal_type.value,
        "age": profile.age,
        "bmi": profile.bmi,
        "kcal_goal": goal.kcal_goal if goal else None,
        "protein_goal": goal.protein_goal if goal else None,
        "carbs_goal": goal.carbs_goal if goal else None,
        "fat_goal": goal.fat_goal if goal else None,
    }


def _serialize_recipe(*, recipe: UserRecipe, product: Product | None) -> dict[str, Any]:
    return {
        "id": int(recipe.id),
        "owner_id": int(recipe.user_id),
        "meal_type": recipe.meal_type.value,
        "title": recipe.title,
        "kcal": float(product.kcal if product else 0.0),
        "protein_g": float(product.protein_g if product else 0.0),
        "carbs_g": float(product.carbs_g if product else 0.0),
        "fat_g": float(product.fat_g if product else 0.0),
        "tags": [_tokenize(str(item)) for item in recipe.tags_json if _tokenize(str(item))],
        "ingredients": [
            _tokenize(str(item.get("name") or ""))
            for item in recipe.ingredients_json
            if isinstance(item, dict) and _tokenize(str(item.get("name") or ""))
        ],
    }


def _serialize_option(option: dict[str, object]) -> dict[str, Any]:
    recipe = option.get("recipe")
    if not isinstance(recipe, dict):
        return {}
    return {
        "id": str(option.get("option_id") or ""),
        "meal_type": str(recipe.get("meal_type") or ""),
        "title": str(recipe.get("title") or ""),
        "kcal": float(recipe.get("nutrition_kcal") or 0.0),
        "protein_g": float(recipe.get("nutrition_protein_g") or 0.0),
        "carbs_g": float(recipe.get("nutrition_carbs_g") or 0.0),
        "fat_g": float(recipe.get("nutrition_fat_g") or 0.0),
        "tags": [_tokenize(str(item)) for item in recipe.get("tags", []) if _tokenize(str(item))],
        "ingredients": [
            _tokenize(str(item.get("name") or ""))
            for item in recipe.get("ingredients", [])
            if isinstance(item, dict) and _tokenize(str(item.get("name") or ""))
        ],
    }


def _tokenize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(part for part in ascii_text.replace("-", " ").replace("_", " ").split() if part)


def _build_reason(*, usernames: list[str], shared_tags: int, shared_ingredients: int) -> str:
    if usernames:
        users_preview = ", ".join(usernames[:3])
        if shared_ingredients > 0:
            return (
                f"Neo4j detecta afinidad con perfiles similares ({users_preview}) "
                "y con ingredientes repetidos entre ellos."
            )
        if shared_tags > 0:
            return (
                f"Neo4j detecta afinidad con perfiles similares ({users_preview}) "
                "y con el mismo estilo de receta."
            )
        return f"Neo4j prioriza esta opcion porque encaja con perfiles similares ({users_preview})."
    return "Neo4j prioriza esta opcion por afinidad con perfiles y objetivos parecidos."


def _build_and_score_graph(
    tx,
    *,
    current_user_id: int,
    users: list[dict[str, Any]],
    recipes: list[dict[str, Any]],
    options: list[dict[str, Any]],
):
    tx.run(
        """
        MATCH (n)
        WHERE n:NutriTrackerUser
           OR n:NutriTrackerRecipe
           OR n:NutriTrackerOption
           OR n:NutriTrackerTag
           OR n:NutriTrackerIngredient
        DETACH DELETE n
        """
    )
    tx.run(
        """
        UNWIND $users AS user
        CREATE (:NutriTrackerUser {
            id: user.id,
            username: user.username,
            sex: user.sex,
            activity_level: user.activity_level,
            goal_type: user.goal_type,
            age: user.age,
            bmi: user.bmi,
            kcal_goal: user.kcal_goal,
            protein_goal: user.protein_goal,
            carbs_goal: user.carbs_goal,
            fat_goal: user.fat_goal
        })
        """,
        users=users,
    )
    tx.run(
        """
        UNWIND $recipes AS recipe
        MATCH (user:NutriTrackerUser {id: recipe.owner_id})
        CREATE (recipe_node:NutriTrackerRecipe {
            id: recipe.id,
            meal_type: recipe.meal_type,
            title: recipe.title,
            kcal: recipe.kcal,
            protein_g: recipe.protein_g,
            carbs_g: recipe.carbs_g,
            fat_g: recipe.fat_g
        })
        CREATE (user)-[:HAS_RECIPE]->(recipe_node)
        FOREACH (tag_name IN recipe.tags |
            MERGE (tag:NutriTrackerTag {name: tag_name})
            CREATE (recipe_node)-[:USES_TAG]->(tag)
        )
        FOREACH (ingredient_name IN recipe.ingredients |
            MERGE (ingredient:NutriTrackerIngredient {name: ingredient_name})
            CREATE (recipe_node)-[:USES_INGREDIENT]->(ingredient)
        )
        """,
        recipes=recipes,
    )
    tx.run(
        """
        UNWIND $options AS option
        CREATE (option_node:NutriTrackerOption {
            id: option.id,
            meal_type: option.meal_type,
            title: option.title,
            kcal: option.kcal,
            protein_g: option.protein_g,
            carbs_g: option.carbs_g,
            fat_g: option.fat_g
        })
        FOREACH (tag_name IN option.tags |
            MERGE (tag:NutriTrackerTag {name: tag_name})
            CREATE (option_node)-[:USES_TAG]->(tag)
        )
        FOREACH (ingredient_name IN option.ingredients |
            MERGE (ingredient:NutriTrackerIngredient {name: ingredient_name})
            CREATE (option_node)-[:USES_INGREDIENT]->(ingredient)
        )
        """,
        options=options,
    )
    result = tx.run(
        """
        MATCH (me:NutriTrackerUser {id: $current_user_id})
        MATCH (other:NutriTrackerUser)-[:HAS_RECIPE]->(recipe:NutriTrackerRecipe)
        WHERE other.id <> me.id
        WITH me, other, recipe,
             (
               CASE WHEN me.goal_type = other.goal_type THEN 2.4 ELSE 0.0 END +
               CASE WHEN me.activity_level = other.activity_level THEN 1.5 ELSE 0.0 END +
               CASE WHEN me.sex = other.sex THEN 0.4 ELSE 0.0 END +
               CASE
                   WHEN me.age IS NULL OR other.age IS NULL THEN 0.0
                   ELSE GREATEST(0.0, 1.0 - abs(toFloat(me.age) - toFloat(other.age)) / 20.0) * 1.2
               END +
               CASE
                   WHEN me.bmi IS NULL OR other.bmi IS NULL THEN 0.0
                   ELSE GREATEST(0.0, 1.0 - abs(toFloat(me.bmi) - toFloat(other.bmi)) / 10.0) * 1.8
               END +
               CASE
                   WHEN me.kcal_goal IS NULL OR other.kcal_goal IS NULL THEN 0.0
                   ELSE GREATEST(0.0, 1.0 - abs(toFloat(me.kcal_goal) - toFloat(other.kcal_goal)) / 900.0) * 1.4
               END
             ) AS profile_score
        WHERE profile_score >= 2.0
        MATCH (option:NutriTrackerOption)
        OPTIONAL MATCH (recipe)-[:USES_TAG]->(shared_tag:NutriTrackerTag)<-[:USES_TAG]-(option)
        WITH other, recipe, option, profile_score, count(DISTINCT shared_tag) AS shared_tags
        OPTIONAL MATCH
            (recipe)-[:USES_INGREDIENT]->(shared_ingredient:NutriTrackerIngredient)<-[:USES_INGREDIENT]-(option)
        WITH
            other,
            recipe,
            option,
            profile_score,
            shared_tags,
            count(DISTINCT shared_ingredient) AS shared_ingredients,
             CASE WHEN recipe.meal_type = option.meal_type THEN 0.8 ELSE 0.0 END AS meal_match,
             GREATEST(
                0.0,
                1.0 - abs(recipe.protein_g - option.protein_g) /
                CASE WHEN option.protein_g < 1.0 THEN 1.0 ELSE option.protein_g END
             ) AS protein_fit,
             GREATEST(
                0.0,
                1.0 - abs(recipe.kcal - option.kcal) /
                CASE WHEN option.kcal < 1.0 THEN 1.0 ELSE option.kcal END
             ) AS kcal_fit
        WITH option,
             sum(
                profile_score * (
                    1.0
                    + shared_tags * 0.35
                    + shared_ingredients * 0.45
                    + meal_match
                    + protein_fit * 0.30
                    + kcal_fit * 0.20
                )
             ) AS raw_score,
             collect(DISTINCT other.username)[0..3] AS similar_usernames,
             max(shared_tags) AS shared_tags,
             max(shared_ingredients) AS shared_ingredients
        RETURN option.id AS option_id, raw_score, similar_usernames, shared_tags, shared_ingredients
        ORDER BY raw_score DESC, option.id ASC
        """,
        current_user_id=current_user_id,
    )
    return [record.data() for record in result]
