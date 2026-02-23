import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  Vibration,
  View,
} from "react-native";
import Slider from "@react-native-community/slider";
import { BarcodeScanningResult, CameraView, useCameraPermissions } from "expo-camera";
import Constants from "expo-constants";
import * as ImagePicker from "expo-image-picker";
import * as SecureStore from "expo-secure-store";
import { StatusBar } from "expo-status-bar";
import Svg, { Circle, G } from "react-native-svg";

type NutritionBasis = "per_100g" | "per_100ml" | "per_serving";
type LookupSource = "local" | "openfoodfacts_imported" | "openfoodfacts_incomplete" | "not_found";
type IntakeMethod = "grams" | "percent_pack" | "units";
type Sex = "male" | "female" | "other";
type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "athlete";
type GoalType = "lose" | "maintain" | "gain";
type MainTab = "dashboard" | "scan" | "history" | "settings";
type AuthStackScreen = "welcome" | "signup" | "login";
type OnboardingStep = 1 | 2 | 3;

type AuthUser = {
  id: number;
  email: string;
  email_verified: boolean;
  onboarding_completed: boolean;
};

type Profile = {
  weight_kg: number;
  height_cm: number;
  age: number | null;
  sex: Sex;
  activity_level: ActivityLevel;
  goal_type: GoalType;
  waist_cm: number | null;
  neck_cm: number | null;
  hip_cm: number | null;
  chest_cm: number | null;
  arm_cm: number | null;
  thigh_cm: number | null;
  bmi: number | null;
  bmi_category: string;
  bmi_color: string;
  body_fat_percent: number | null;
  body_fat_category: string;
  body_fat_color: string;
};

type GoalPayload = {
  kcal_goal: number;
  protein_goal: number;
  fat_goal: number;
  carbs_goal: number;
};

type GoalFeedback = {
  realistic: boolean;
  notes: string[];
};

type DailyGoalResponse = GoalPayload & {
  feedback: GoalFeedback;
};

type Product = {
  id: number;
  barcode: string | null;
  name: string;
  brand: string | null;
  image_url: string | null;
  nutrition_basis: NutritionBasis;
  serving_size_g: number | null;
  net_weight_g: number | null;
  kcal: number;
  protein_g: number;
  fat_g: number;
  sat_fat_g: number | null;
  carbs_g: number;
  sugars_g: number | null;
  fiber_g: number | null;
  salt_g: number | null;
  data_confidence: string;
};

type ProductPreference = {
  method: IntakeMethod;
  quantity_g: number | null;
  quantity_units: number | null;
  percent_pack: number | null;
};

type ProductLookupResponse = {
  source: LookupSource;
  product: Product | null;
  missing_fields: string[];
  message: string | null;
  preferred_serving: ProductPreference | null;
};

type LabelPhotoResponse = {
  created: boolean;
  product: Product | null;
  missing_fields: string[];
  questions: string[];
};

type Nutrients = {
  kcal: number;
  protein_g: number;
  fat_g: number;
  sat_fat_g: number;
  carbs_g: number;
  sugars_g: number;
  fiber_g: number;
  salt_g: number;
};

type Intake = {
  id: number;
  product_id: number;
  product_name: string | null;
  method: IntakeMethod;
  quantity_g: number | null;
  quantity_units: number | null;
  percent_pack: number | null;
  created_at: string;
  nutrients: Nutrients;
};

type DaySummary = {
  date: string;
  goal: GoalPayload | null;
  consumed: Nutrients;
  remaining: Nutrients | null;
  intakes: Intake[];
};

type CalendarDayEntry = {
  date: string;
  intake_count: number;
  kcal: number;
};

type CalendarMonthResponse = {
  month: string;
  days: CalendarDayEntry[];
};

type AnalysisResponse = {
  profile: Profile;
  recommended_goal: GoalPayload;
  goal_feedback_today: GoalFeedback | null;
};

type RegisterResponse = {
  user_id: number;
  email: string;
  email_verified: boolean;
  onboarding_completed: boolean;
  message: string;
  debug_verification_code: string | null;
};

type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
  profile: Profile | null;
};

type MeResponse = {
  user: AuthUser;
  profile: Profile | null;
};

type ProfileInput = {
  weight_kg: number;
  height_cm: number;
  age: number | null;
  sex: Sex;
  activity_level: ActivityLevel;
  goal_type: GoalType;
  waist_cm: number | null;
  neck_cm: number | null;
  hip_cm: number | null;
  chest_cm: number | null;
  arm_cm: number | null;
  thigh_cm: number | null;
};

type GoalInputDraft = {
  kcal_goal: string;
  protein_goal: string;
  fat_goal: string;
  carbs_goal: string;
};

type RegisterInput = {
  email: string;
  password: string;
};

type LoginInput = {
  email: string;
  password: string;
};

type AuthContextValue = {
  loading: boolean;
  token: string | null;
  user: AuthUser | null;
  profile: Profile | null;
  apiBaseUrl: string;
  pendingVerificationEmail: string | null;
  otpHint: string | null;
  register: (input: RegisterInput) => Promise<RegisterResponse>;
  login: (input: LoginInput) => Promise<void>;
  verifyEmail: (email: string, code: string) => Promise<void>;
  resendCode: (email: string) => Promise<void>;
  clearPendingVerification: () => void;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  saveProfile: (payload: ProfileInput) => Promise<Profile>;
  fetchAnalysis: (day: string) => Promise<AnalysisResponse>;
  fetchGoal: (day: string) => Promise<DailyGoalResponse | null>;
  saveGoal: (day: string, goal: GoalPayload) => Promise<DailyGoalResponse>;
  fetchDaySummary: (day: string) => Promise<DaySummary>;
  fetchCalendar: (yearMonth: string) => Promise<CalendarMonthResponse>;
  lookupByBarcode: (ean: string) => Promise<ProductLookupResponse>;
  createProductFromLabel: (input: {
    barcode: string;
    name: string;
    brand: string;
    labelText: string;
    photos: string[];
  }) => Promise<LabelPhotoResponse>;
  createIntake: (payload: {
    product_id: number;
    method: IntakeMethod;
    quantity_g?: number;
    quantity_units?: number;
    percent_pack?: number;
  }) => Promise<Intake>;
  setApiBaseUrl: (url: string) => void;
  checkHealth: (url?: string) => Promise<boolean>;
};

type Segment = {
  label: string;
  value: number;
  color: string;
};

const TOKEN_STORAGE_KEY = "nutri_tracker_access_token";

const theme = {
  bg: "#05070d",
  panel: "#0f1421",
  panelSoft: "#131a2b",
  border: "#202b44",
  text: "#edf4ff",
  muted: "#8ea4cb",
  accent: "#2cf0c5",
  accentSoft: "#17463f",
  danger: "#ff819e",
  warning: "#ffc778",
  ok: "#70e39f",
  blue: "#5ca0ff",
  yellow: "#f6c453",
  red: "#f77979",
};

const authContext = createContext<AuthContextValue | undefined>(undefined);

function useAuth(): AuthContextValue {
  const value = useContext(authContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}

function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "";
  }

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, "");
  }

  return `http://${trimmed.replace(/\/+$/, "")}`;
}

function getExpoHostIp(): string | null {
  const hostUri =
    Constants.expoConfig?.hostUri ??
    (Constants as { manifest2?: { extra?: { expoClient?: { hostUri?: string } } } }).manifest2?.extra?.expoClient
      ?.hostUri;

  if (!hostUri) {
    return null;
  }

  const host = hostUri.split(":")[0]?.trim();
  if (!host || host === "127.0.0.1" || host === "localhost") {
    return null;
  }
  return host;
}

function inferApiBaseUrl(): string {
  const envUrl = normalizeBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL ?? "");
  if (envUrl && !envUrl.includes("localhost")) {
    return envUrl;
  }

  const hostIp = getExpoHostIp();
  if (hostIp) {
    return `http://${hostIp}:8000`;
  }

  if (Platform.OS === "android") {
    return "http://10.0.2.2:8000";
  }

  return envUrl || "http://localhost:8000";
}

function parseApiError(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Unexpected error";
  }

  if (error.message.includes("Network request failed")) {
    return "Network request failed. Revisa la URL API y que el backend esté corriendo.";
  }

  return error.message;
}

function formatDateLocal(day: Date): string {
  const y = day.getFullYear();
  const m = String(day.getMonth() + 1).padStart(2, "0");
  const d = String(day.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatMonth(day: Date): string {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}`;
}

function monthFromKey(key: string): Date {
  const [yearRaw, monthRaw] = key.split("-");
  const year = Number(yearRaw);
  const month = Number(monthRaw);
  if (!Number.isFinite(year) || !Number.isFinite(month) || month < 1 || month > 12) {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  }
  return new Date(year, month - 1, 1);
}

function moveMonth(key: string, delta: number): string {
  const day = monthFromKey(key);
  day.setMonth(day.getMonth() + delta);
  return formatMonth(day);
}

function toOptionalNumber(input: string): number | null {
  const parsed = Number(input.trim().replace(",", "."));
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function toPositiveNumberOrNull(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) {
    return null;
  }
  return toOptionalNumber(trimmed);
}

function bmiValue(weightKg: number | null, heightCm: number | null): number | null {
  if (!weightKg || !heightCm || heightCm <= 0) {
    return null;
  }
  return Math.round((weightKg / ((heightCm / 100) ** 2)) * 100) / 100;
}

function bmiCategory(value: number | null): { label: string; color: string; pct: number } {
  if (value === null) {
    return { label: "N/A", color: theme.muted, pct: 0 };
  }
  if (value < 18.5) {
    return { label: "underweight", color: theme.blue, pct: 0.2 };
  }
  if (value < 25) {
    return { label: "normal", color: theme.ok, pct: 0.45 };
  }
  if (value < 30) {
    return { label: "overweight", color: theme.yellow, pct: 0.72 };
  }
  return { label: "obesity", color: theme.red, pct: 0.92 };
}

function estimateBodyFatPreview(input: {
  sex: Sex;
  heightCm: number | null;
  waistCm: number | null;
  neckCm: number | null;
  hipCm: number | null;
}): number | null {
  const height = input.heightCm;
  if (!height) {
    return null;
  }

  const toInches = (value: number): number => value / 2.54;

  if (input.sex === "male") {
    if (!input.waistCm || !input.neckCm) {
      return null;
    }

    const waist = toInches(input.waistCm);
    const neck = toInches(input.neckCm);
    const h = toInches(height);
    if (waist <= neck) {
      return null;
    }

    const result = 495 / (1.0324 - 0.19077 * Math.log10(waist - neck) + 0.15456 * Math.log10(h)) - 450;
    return Math.round(Math.max(result, 2) * 100) / 100;
  }

  if (input.sex === "female") {
    if (!input.waistCm || !input.neckCm || !input.hipCm) {
      return null;
    }

    const waist = toInches(input.waistCm);
    const neck = toInches(input.neckCm);
    const hip = toInches(input.hipCm);
    const h = toInches(height);
    if (waist + hip <= neck) {
      return null;
    }

    const result = 495 / (1.29579 - 0.35004 * Math.log10(waist + hip - neck) + 0.221 * Math.log10(h)) - 450;
    return Math.round(Math.max(result, 5) * 100) / 100;
  }

  return null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function calendarCells(monthKey: string): Array<number | null> {
  const base = monthFromKey(monthKey);
  const year = base.getFullYear();
  const month = base.getMonth();

  const first = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);

  const jsWeekday = first.getDay();
  const mondayStart = jsWeekday === 0 ? 6 : jsWeekday - 1;

  const cells: Array<number | null> = [];
  for (let i = 0; i < mondayStart; i += 1) {
    cells.push(null);
  }

  for (let day = 1; day <= last.getDate(); day += 1) {
    cells.push(day);
  }

  while (cells.length % 7 !== 0) {
    cells.push(null);
  }

  return cells;
}

function dayFromMonthAndCell(monthKey: string, day: number): string {
  const month = monthFromKey(monthKey);
  return `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function AuthProvider({ children }: { children: import("react").ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [pendingVerificationEmail, setPendingVerificationEmail] = useState<string | null>(null);
  const [otpHint, setOtpHint] = useState<string | null>(null);
  const [apiBaseUrl, setApiBaseUrl] = useState(inferApiBaseUrl());

  const request = useCallback(
    async <T,>(path: string, init?: RequestInit, authToken?: string | null): Promise<T> => {
      const headers = new Headers(init?.headers ?? {});
      const effectiveToken = authToken ?? token;
      if (effectiveToken) {
        headers.set("Authorization", `Bearer ${effectiveToken}`);
      }

      const response = await fetch(`${normalizeBaseUrl(apiBaseUrl)}${path}`, {
        ...init,
        headers,
      });

      const text = await response.text();
      let body: unknown = null;

      if (text) {
        try {
          body = JSON.parse(text) as unknown;
        } catch {
          body = text;
        }
      }

      if (!response.ok) {
        const detail =
          typeof body === "object" && body !== null
            ? ((body as { detail?: string }).detail ?? (body as { message?: string }).message)
            : undefined;
        throw new Error(detail ?? `HTTP ${response.status}`);
      }

      return body as T;
    },
    [apiBaseUrl, token],
  );

  const checkHealth = useCallback(
    async (url?: string): Promise<boolean> => {
      const target = normalizeBaseUrl(url ?? apiBaseUrl);
      if (!target) {
        return false;
      }

      try {
        const response = await fetch(`${target}/health`);
        if (!response.ok) {
          return false;
        }
        const body = (await response.json()) as { status?: string };
        return body.status === "ok";
      } catch {
        return false;
      }
    },
    [apiBaseUrl],
  );

  const boot = useCallback(async () => {
    setLoading(true);
    try {
      const storedToken = await SecureStore.getItemAsync(TOKEN_STORAGE_KEY);
      if (!storedToken) {
        setToken(null);
        setUser(null);
        setProfile(null);
        return;
      }

      const me = await request<MeResponse>("/me", undefined, storedToken);
      setToken(storedToken);
      setUser(me.user);
      setProfile(me.profile);
    } catch {
      await SecureStore.deleteItemAsync(TOKEN_STORAGE_KEY);
      setToken(null);
      setUser(null);
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    void boot();
  }, [boot]);

  const persistAuth = useCallback(async (response: AuthResponse) => {
    setToken(response.access_token);
    setUser(response.user);
    setProfile(response.profile);
    setPendingVerificationEmail(null);
    await SecureStore.setItemAsync(TOKEN_STORAGE_KEY, response.access_token);
  }, []);

  const register = useCallback(
    async (input: RegisterInput): Promise<RegisterResponse> => {
      const response = await request<RegisterResponse>("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      });

      setPendingVerificationEmail(response.email);
      setOtpHint(response.debug_verification_code);
      setUser(null);
      setProfile(null);
      setToken(null);
      await SecureStore.deleteItemAsync(TOKEN_STORAGE_KEY);
      return response;
    },
    [request],
  );

  const login = useCallback(
    async (input: LoginInput): Promise<void> => {
      const response = await request<AuthResponse>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      });
      await persistAuth(response);
      setOtpHint(null);
    },
    [persistAuth, request],
  );

  const verifyEmail = useCallback(
    async (email: string, code: string): Promise<void> => {
      const response = await request<AuthResponse>("/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      await persistAuth(response);
      setOtpHint(null);
    },
    [persistAuth, request],
  );

  const resendCode = useCallback(
    async (email: string): Promise<void> => {
      const response = await request<RegisterResponse>("/auth/resend-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setOtpHint(response.debug_verification_code);
      setPendingVerificationEmail(response.email);
    },
    [request],
  );

  const clearPendingVerification = useCallback(() => {
    setPendingVerificationEmail(null);
    setOtpHint(null);
  }, []);

  const logout = useCallback(async () => {
    await SecureStore.deleteItemAsync(TOKEN_STORAGE_KEY);
    setToken(null);
    setUser(null);
    setProfile(null);
    setPendingVerificationEmail(null);
    setOtpHint(null);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!token) {
      return;
    }
    const me = await request<MeResponse>("/me");
    setUser(me.user);
    setProfile(me.profile);
  }, [request, token]);

  const saveProfile = useCallback(
    async (payload: ProfileInput): Promise<Profile> => {
      const response = await request<Profile>("/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setProfile(response);
      await refreshMe();
      return response;
    },
    [refreshMe, request],
  );

  const fetchAnalysis = useCallback(
    async (day: string): Promise<AnalysisResponse> => request<AnalysisResponse>(`/me/analysis?day=${day}`),
    [request],
  );

  const fetchGoal = useCallback(
    async (day: string): Promise<DailyGoalResponse | null> => {
      try {
        return await request<DailyGoalResponse | null>(`/goals/${day}`);
      } catch (error) {
        if (error instanceof Error && error.message.includes("404")) {
          return null;
        }
        throw error;
      }
    },
    [request],
  );

  const saveGoal = useCallback(
    async (day: string, goal: GoalPayload): Promise<DailyGoalResponse> => {
      const response = await request<DailyGoalResponse>(`/goals/${day}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(goal),
      });
      await refreshMe();
      return response;
    },
    [refreshMe, request],
  );

  const fetchDaySummary = useCallback(
    async (day: string): Promise<DaySummary> => request<DaySummary>(`/days/${day}/summary`),
    [request],
  );

  const fetchCalendar = useCallback(
    async (yearMonth: string): Promise<CalendarMonthResponse> => request<CalendarMonthResponse>(`/calendar/${yearMonth}`),
    [request],
  );

  const lookupByBarcode = useCallback(
    async (ean: string): Promise<ProductLookupResponse> => request<ProductLookupResponse>(`/products/by_barcode/${ean}`),
    [request],
  );

  const createProductFromLabel = useCallback(
    async (input: {
      barcode: string;
      name: string;
      brand: string;
      labelText: string;
      photos: string[];
    }): Promise<LabelPhotoResponse> => {
      const form = new FormData();
      form.append("barcode", input.barcode);
      form.append("name", input.name);
      if (input.brand.trim()) {
        form.append("brand", input.brand.trim());
      }
      if (input.labelText.trim()) {
        form.append("label_text", input.labelText.trim());
      }

      input.photos.forEach((uri, index) => {
        const name = uri.split("/").pop() || `label-${index + 1}.jpg`;
        form.append(
          "photos",
          {
            uri,
            name,
            type: "image/jpeg",
          } as unknown as Blob,
        );
      });

      return request<LabelPhotoResponse>("/products/from_label_photo", {
        method: "POST",
        body: form,
      });
    },
    [request],
  );

  const createIntake = useCallback(
    async (payload: {
      product_id: number;
      method: IntakeMethod;
      quantity_g?: number;
      quantity_units?: number;
      percent_pack?: number;
    }): Promise<Intake> => {
      return request<Intake>("/intakes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    },
    [request],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      loading,
      token,
      user,
      profile,
      apiBaseUrl,
      pendingVerificationEmail,
      otpHint,
      register,
      login,
      verifyEmail,
      resendCode,
      clearPendingVerification,
      logout,
      refreshMe,
      saveProfile,
      fetchAnalysis,
      fetchGoal,
      saveGoal,
      fetchDaySummary,
      fetchCalendar,
      lookupByBarcode,
      createProductFromLabel,
      createIntake,
      setApiBaseUrl: (url: string) => setApiBaseUrl(normalizeBaseUrl(url)),
      checkHealth,
    }),
    [
      apiBaseUrl,
      checkHealth,
      clearPendingVerification,
      createIntake,
      createProductFromLabel,
      fetchAnalysis,
      fetchCalendar,
      fetchDaySummary,
      fetchGoal,
      loading,
      login,
      logout,
      lookupByBarcode,
      otpHint,
      pendingVerificationEmail,
      profile,
      refreshMe,
      register,
      resendCode,
      saveGoal,
      saveProfile,
      token,
      user,
      verifyEmail,
    ],
  );

  return <authContext.Provider value={value}>{children}</authContext.Provider>;
}

function LoadingGate() {
  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={theme.accent} />
        <Text style={styles.helperText}>Cargando estado de sesión...</Text>
      </View>
    </SafeAreaView>
  );
}

function AppHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <View style={styles.headerWrap}>
      <Text style={styles.headerTitle}>{title}</Text>
      <Text style={styles.headerSubtitle}>{subtitle}</Text>
    </View>
  );
}

function InputField(props: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  keyboardType?: "default" | "email-address" | "numeric";
  secureTextEntry?: boolean;
  autoCapitalize?: "none" | "sentences" | "words" | "characters";
  placeholder?: string;
}) {
  return (
    <View style={styles.fieldWrap}>
      <Text style={styles.fieldLabel}>{props.label}</Text>
      <TextInput
        value={props.value}
        onChangeText={props.onChangeText}
        keyboardType={props.keyboardType ?? "default"}
        secureTextEntry={props.secureTextEntry}
        autoCapitalize={props.autoCapitalize ?? "none"}
        placeholder={props.placeholder}
        placeholderTextColor={theme.muted}
        style={styles.input}
      />
    </View>
  );
}

function PrimaryButton(props: { title: string; onPress: () => void; loading?: boolean; disabled?: boolean }) {
  const disabled = props.disabled || props.loading;
  return (
    <Pressable onPress={props.onPress} disabled={disabled} style={[styles.primaryButton, disabled && styles.disabledButton]}>
      {props.loading ? <ActivityIndicator color={theme.bg} /> : <Text style={styles.primaryButtonText}>{props.title}</Text>}
    </Pressable>
  );
}

function SecondaryButton(props: { title: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable onPress={props.onPress} disabled={props.disabled} style={[styles.secondaryButton, props.disabled && styles.disabledButton]}>
      <Text style={styles.secondaryButtonText}>{props.title}</Text>
    </Pressable>
  );
}

function WelcomeScreen({ onCreate, onLogin }: { onCreate: () => void; onLogin: () => void }) {
  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.authScroll} keyboardShouldPersistTaps="handled">
        <View style={styles.brandCard}>
          <Text style={styles.brandEyebrow}>NUTRI TRACKER</Text>
          <Text style={styles.brandTitle}>Control nutricional diario, claro y sin ruido</Text>
          <Text style={styles.brandText}>
            Escanea, registra porciones y visualiza tu progreso con objetivos realistas según tu perfil.
          </Text>
        </View>

        <PrimaryButton title="Crear cuenta" onPress={onCreate} />
        <SecondaryButton title="Iniciar sesión" onPress={onLogin} />
      </ScrollView>
    </SafeAreaView>
  );
}

function SignupScreen({ onBack }: { onBack: () => void }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email.trim() || !password.trim()) {
      Alert.alert("Faltan datos", "Completa email y contraseña.");
      return;
    }
    if (password.length < 8) {
      Alert.alert("Contraseña", "Debe tener al menos 8 caracteres.");
      return;
    }
    if (password !== confirmPassword) {
      Alert.alert("Contraseña", "Las contraseñas no coinciden.");
      return;
    }

    setLoading(true);
    try {
      const response = await auth.register({ email: email.trim().toLowerCase(), password });
      Alert.alert("Cuenta creada", response.message);
    } catch (error) {
      Alert.alert("Registro", parseApiError(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex1}>
        <ScrollView contentContainerStyle={styles.authScroll} keyboardShouldPersistTaps="handled">
          <AppHeader title="Crear cuenta" subtitle="Solo email y contraseña, luego verificas con código OTP." />

          <InputField label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" />
          <InputField label="Contraseña" value={password} onChangeText={setPassword} secureTextEntry />
          <InputField label="Confirmar contraseña" value={confirmPassword} onChangeText={setConfirmPassword} secureTextEntry />

          <PrimaryButton title="Crear cuenta" onPress={submit} loading={loading} />
          <SecondaryButton title="Volver" onPress={onBack} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function LoginScreen({ onBack }: { onBack: () => void }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email.trim() || !password.trim()) {
      Alert.alert("Faltan datos", "Completa email y contraseña.");
      return;
    }

    setLoading(true);
    try {
      await auth.login({ email: email.trim().toLowerCase(), password });
    } catch (error) {
      Alert.alert("Login", parseApiError(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex1}>
        <ScrollView contentContainerStyle={styles.authScroll} keyboardShouldPersistTaps="handled">
          <AppHeader title="Iniciar sesión" subtitle="Si el email no está verificado, pasarás directo a validarlo." />

          <InputField label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" />
          <InputField label="Contraseña" value={password} onChangeText={setPassword} secureTextEntry />

          <PrimaryButton title="Entrar" onPress={submit} loading={loading} />
          <SecondaryButton title="Volver" onPress={onBack} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function AuthStack() {
  const [screen, setScreen] = useState<AuthStackScreen>("welcome");

  if (screen === "signup") {
    return <SignupScreen onBack={() => setScreen("welcome")} />;
  }

  if (screen === "login") {
    return <LoginScreen onBack={() => setScreen("welcome")} />;
  }

  return <WelcomeScreen onCreate={() => setScreen("signup")} onLogin={() => setScreen("login")} />;
}

function VerifyEmailOnlyScreen() {
  const auth = useAuth();
  const email = auth.user?.email ?? auth.pendingVerificationEmail;
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) {
      return;
    }
    const timer = setInterval(() => setCooldown((current) => Math.max(current - 1, 0)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  if (!email) {
    return (
      <SafeAreaView style={styles.screen}>
        <View style={styles.centered}>
          <Text style={styles.helperText}>Falta email para verificar.</Text>
          <SecondaryButton title="Volver" onPress={auth.clearPendingVerification} />
        </View>
      </SafeAreaView>
    );
  }

  const verify = async () => {
    if (code.trim().length < 4) {
      Alert.alert("Código", "Introduce un código válido.");
      return;
    }

    setLoading(true);
    try {
      await auth.verifyEmail(email, code.trim());
    } catch (error) {
      Alert.alert("Verificación", parseApiError(error));
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    setResending(true);
    try {
      await auth.resendCode(email);
      setCooldown(60);
      Alert.alert("Código enviado", "Revisa tu email o el log del backend en modo dev.");
    } catch (error) {
      Alert.alert("Reenviar", parseApiError(error));
    } finally {
      setResending(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex1}>
        <ScrollView contentContainerStyle={styles.authScroll} keyboardShouldPersistTaps="handled">
          <AppHeader title="Verificar email" subtitle={`Código OTP de 6 dígitos para ${email}`} />

          <InputField
            label="Código"
            value={code}
            onChangeText={setCode}
            keyboardType="numeric"
            autoCapitalize="none"
            placeholder="123456"
          />

          {auth.otpHint ? <Text style={styles.devHint}>DEV OTP: {auth.otpHint}</Text> : null}

          <PrimaryButton title="Verificar" onPress={verify} loading={loading} />
          <SecondaryButton
            title={cooldown > 0 ? `Reenviar en ${cooldown}s` : "Reenviar código"}
            onPress={resend}
            disabled={cooldown > 0 || resending}
          />

          {auth.user ? <SecondaryButton title="Cerrar sesión" onPress={() => void auth.logout()} /> : null}
          {!auth.user ? <SecondaryButton title="Volver" onPress={auth.clearPendingVerification} /> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function ChoiceRow<T extends string>(props: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: Array<{ label: string; value: T }>;
}) {
  return (
    <View style={styles.fieldWrap}>
      <Text style={styles.fieldLabel}>{props.label}</Text>
      <View style={styles.chipsRow}>
        {props.options.map((option) => {
          const active = option.value === props.value;
          return (
            <Pressable
              key={option.value}
              onPress={() => props.onChange(option.value)}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function BmiBar({ value }: { value: number | null }) {
  const category = bmiCategory(value);
  return (
    <View style={styles.metricCard}>
      <Text style={styles.metricTitle}>IMC estimado</Text>
      <Text style={styles.metricValue}>{value ? value.toFixed(2) : "-"}</Text>
      <Text style={[styles.metricBadge, { color: category.color }]}>{category.label}</Text>
      <View style={styles.bmiTrack}>
        <View style={[styles.bmiBand, { backgroundColor: theme.blue }]} />
        <View style={[styles.bmiBand, { backgroundColor: theme.ok }]} />
        <View style={[styles.bmiBand, { backgroundColor: theme.yellow }]} />
        <View style={[styles.bmiBand, { backgroundColor: theme.red }]} />
      </View>
      <View style={[styles.bmiPointer, { left: `${category.pct * 100}%`, backgroundColor: category.color }]} />
      <Text style={styles.helperText}>underweight / normal / overweight / obesity</Text>
    </View>
  );
}

function OnboardingWizard() {
  const auth = useAuth();
  const [step, setStep] = useState<OnboardingStep>(1);
  const [saving, setSaving] = useState(false);

  const [weight, setWeight] = useState(auth.profile?.weight_kg ? String(auth.profile.weight_kg) : "");
  const [height, setHeight] = useState(auth.profile?.height_cm ? String(auth.profile.height_cm) : "");
  const [age, setAge] = useState(auth.profile?.age ? String(auth.profile.age) : "");
  const [sex, setSex] = useState<Sex>(auth.profile?.sex ?? "other");
  const [activityLevel, setActivityLevel] = useState<ActivityLevel>(auth.profile?.activity_level ?? "moderate");
  const [goalType, setGoalType] = useState<GoalType>(auth.profile?.goal_type ?? "maintain");

  const [waist, setWaist] = useState(auth.profile?.waist_cm ? String(auth.profile.waist_cm) : "");
  const [neck, setNeck] = useState(auth.profile?.neck_cm ? String(auth.profile.neck_cm) : "");
  const [hip, setHip] = useState(auth.profile?.hip_cm ? String(auth.profile.hip_cm) : "");
  const [chest, setChest] = useState(auth.profile?.chest_cm ? String(auth.profile.chest_cm) : "");
  const [arm, setArm] = useState(auth.profile?.arm_cm ? String(auth.profile.arm_cm) : "");
  const [thigh, setThigh] = useState(auth.profile?.thigh_cm ? String(auth.profile.thigh_cm) : "");

  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [goalDraft, setGoalDraft] = useState<GoalInputDraft>({
    kcal_goal: "",
    protein_goal: "",
    fat_goal: "",
    carbs_goal: "",
  });
  const [goalFeedback, setGoalFeedback] = useState<GoalFeedback | null>(null);

  const today = useMemo(() => formatDateLocal(new Date()), []);

  const numericWeight = toPositiveNumberOrNull(weight);
  const numericHeight = toPositiveNumberOrNull(height);
  const currentBmi = bmiValue(numericWeight, numericHeight);

  const draftBodyFat = estimateBodyFatPreview({
    sex,
    heightCm: numericHeight,
    waistCm: toOptionalNumber(waist),
    neckCm: toOptionalNumber(neck),
    hipCm: toOptionalNumber(hip),
  });

  const buildProfilePayload = useCallback(
    (clearOptionalMeasures: boolean): ProfileInput | null => {
      const payloadWeight = toPositiveNumberOrNull(weight);
      const payloadHeight = toPositiveNumberOrNull(height);
      if (!payloadWeight || !payloadHeight) {
        return null;
      }

      const optionalAge = age.trim() ? Number(age.trim()) : null;
      if (optionalAge !== null && (!Number.isFinite(optionalAge) || optionalAge < 13 || optionalAge > 120)) {
        return null;
      }

      return {
        weight_kg: payloadWeight,
        height_cm: payloadHeight,
        age: optionalAge,
        sex,
        activity_level: activityLevel,
        goal_type: goalType,
        waist_cm: clearOptionalMeasures ? null : toOptionalNumber(waist),
        neck_cm: clearOptionalMeasures ? null : toOptionalNumber(neck),
        hip_cm: clearOptionalMeasures ? null : toOptionalNumber(hip),
        chest_cm: clearOptionalMeasures ? null : toOptionalNumber(chest),
        arm_cm: clearOptionalMeasures ? null : toOptionalNumber(arm),
        thigh_cm: clearOptionalMeasures ? null : toOptionalNumber(thigh),
      };
    },
    [activityLevel, age, arm, chest, goalType, height, hip, neck, sex, thigh, waist, weight],
  );

  const goToStepThree = async (skipMeasures: boolean) => {
    const profilePayload = buildProfilePayload(skipMeasures);
    if (!profilePayload) {
      Alert.alert("Perfil", "Revisa los datos básicos y la edad opcional.");
      return;
    }

    setSaving(true);
    try {
      await auth.saveProfile(profilePayload);
      const nextAnalysis = await auth.fetchAnalysis(today);
      setAnalysis(nextAnalysis);

      const existingGoal = await auth.fetchGoal(today);
      if (existingGoal) {
        setGoalDraft({
          kcal_goal: String(existingGoal.kcal_goal),
          protein_goal: String(existingGoal.protein_goal),
          fat_goal: String(existingGoal.fat_goal),
          carbs_goal: String(existingGoal.carbs_goal),
        });
        setGoalFeedback(existingGoal.feedback);
      } else {
        setGoalDraft({
          kcal_goal: String(nextAnalysis.recommended_goal.kcal_goal),
          protein_goal: String(nextAnalysis.recommended_goal.protein_goal),
          fat_goal: String(nextAnalysis.recommended_goal.fat_goal),
          carbs_goal: String(nextAnalysis.recommended_goal.carbs_goal),
        });
        setGoalFeedback(nextAnalysis.goal_feedback_today);
      }

      setStep(3);
    } catch (error) {
      Alert.alert("Onboarding", parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  const finishOnboarding = async () => {
    const payload: GoalPayload = {
      kcal_goal: Number(goalDraft.kcal_goal),
      protein_goal: Number(goalDraft.protein_goal),
      fat_goal: Number(goalDraft.fat_goal),
      carbs_goal: Number(goalDraft.carbs_goal),
    };

    if (!Number.isFinite(payload.kcal_goal) || payload.kcal_goal <= 0) {
      Alert.alert("Objetivo", "Kcal inválidas.");
      return;
    }

    setSaving(true);
    try {
      const response = await auth.saveGoal(today, payload);
      setGoalFeedback(response.feedback);
      await auth.refreshMe();
    } catch (error) {
      Alert.alert("Objetivo", parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex1}>
        <ScrollView contentContainerStyle={styles.authScroll} keyboardShouldPersistTaps="handled">
          <AppHeader title="Onboarding" subtitle={`Paso ${step} de 3`} />

          {step === 1 ? (
            <View style={styles.sectionCard}>
              <Text style={styles.sectionTitle}>Paso 1: datos básicos</Text>
              <InputField label="Peso (kg)" value={weight} onChangeText={setWeight} keyboardType="numeric" />
              <InputField label="Altura (cm)" value={height} onChangeText={setHeight} keyboardType="numeric" />
              <InputField label="Edad (opcional)" value={age} onChangeText={setAge} keyboardType="numeric" />

              <ChoiceRow
                label="Sexo"
                value={sex}
                onChange={setSex}
                options={[
                  { label: "Masculino", value: "male" },
                  { label: "Femenino", value: "female" },
                  { label: "Otro", value: "other" },
                ]}
              />

              <ChoiceRow
                label="Actividad"
                value={activityLevel}
                onChange={setActivityLevel}
                options={[
                  { label: "Sedentario", value: "sedentary" },
                  { label: "Ligero", value: "light" },
                  { label: "Moderado", value: "moderate" },
                  { label: "Activo", value: "active" },
                  { label: "Atleta", value: "athlete" },
                ]}
              />

              <ChoiceRow
                label="Objetivo"
                value={goalType}
                onChange={setGoalType}
                options={[
                  { label: "Perder", value: "lose" },
                  { label: "Mantener", value: "maintain" },
                  { label: "Ganar", value: "gain" },
                ]}
              />

              <BmiBar value={currentBmi} />

              <PrimaryButton title="Continuar" onPress={() => setStep(2)} />
            </View>
          ) : null}

          {step === 2 ? (
            <View style={styles.sectionCard}>
              <Text style={styles.sectionTitle}>Paso 2: medidas corporales (opcional)</Text>
              <InputField label="Cintura (cm)" value={waist} onChangeText={setWaist} keyboardType="numeric" />
              <InputField label="Cuello (cm)" value={neck} onChangeText={setNeck} keyboardType="numeric" />
              <InputField label="Cadera (cm)" value={hip} onChangeText={setHip} keyboardType="numeric" />
              <InputField label="Pecho (cm)" value={chest} onChangeText={setChest} keyboardType="numeric" />
              <InputField label="Brazo (cm)" value={arm} onChangeText={setArm} keyboardType="numeric" />
              <InputField label="Muslo (cm)" value={thigh} onChangeText={setThigh} keyboardType="numeric" />

              <View style={styles.metricCard}>
                <Text style={styles.metricTitle}>% grasa estimado</Text>
                {draftBodyFat !== null ? (
                  <Text style={styles.metricValue}>{draftBodyFat.toFixed(2)}%</Text>
                ) : (
                  <Text style={styles.helperText}>
                    Para estimación más precisa añade cintura y cuello (y cadera si aplica).
                  </Text>
                )}
              </View>

              <PrimaryButton title="Continuar" onPress={() => void goToStepThree(false)} loading={saving} />
              <SecondaryButton title="Saltar" onPress={() => void goToStepThree(true)} disabled={saving} />
              <SecondaryButton title="Volver" onPress={() => setStep(1)} disabled={saving} />
            </View>
          ) : null}

          {step === 3 ? (
            <View style={styles.sectionCard}>
              <Text style={styles.sectionTitle}>Paso 3: objetivos diarios</Text>

              {analysis ? (
                <View style={styles.recoBox}>
                  <Text style={styles.recoTitle}>Rango recomendado según tu perfil</Text>
                  <Text style={styles.helperText}>kcal {analysis.recommended_goal.kcal_goal}</Text>
                  <Text style={styles.helperText}>prote {analysis.recommended_goal.protein_goal} g</Text>
                  <Text style={styles.helperText}>grasa {analysis.recommended_goal.fat_goal} g</Text>
                  <Text style={styles.helperText}>carbs {analysis.recommended_goal.carbs_goal} g</Text>
                </View>
              ) : null}

              <InputField
                label="Kcal"
                value={goalDraft.kcal_goal}
                onChangeText={(value) => setGoalDraft((current) => ({ ...current, kcal_goal: value }))}
                keyboardType="numeric"
              />
              <InputField
                label="Proteína (g)"
                value={goalDraft.protein_goal}
                onChangeText={(value) => setGoalDraft((current) => ({ ...current, protein_goal: value }))}
                keyboardType="numeric"
              />
              <InputField
                label="Grasa (g)"
                value={goalDraft.fat_goal}
                onChangeText={(value) => setGoalDraft((current) => ({ ...current, fat_goal: value }))}
                keyboardType="numeric"
              />
              <InputField
                label="Carbs (g)"
                value={goalDraft.carbs_goal}
                onChangeText={(value) => setGoalDraft((current) => ({ ...current, carbs_goal: value }))}
                keyboardType="numeric"
              />

              {goalFeedback ? (
                <View style={[styles.feedbackBox, !goalFeedback.realistic && styles.feedbackBoxWarning]}>
                  <Text style={styles.feedbackTitle}>{goalFeedback.realistic ? "Objetivo razonable" : "Revisa este objetivo"}</Text>
                  {goalFeedback.notes.map((note) => (
                    <Text key={note} style={styles.feedbackLine}>
                      - {note}
                    </Text>
                  ))}
                </View>
              ) : null}

              <PrimaryButton title="Finalizar onboarding" onPress={() => void finishOnboarding()} loading={saving} />
              <SecondaryButton title="Volver" onPress={() => setStep(2)} disabled={saving} />
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function RingProgress(props: {
  label: string;
  consumed: number;
  goal: number;
  color: string;
  unit: string;
}) {
  const size = 116;
  const stroke = 10;
  const radius = (size - stroke) / 2;
  const circle = 2 * Math.PI * radius;
  const safeGoal = props.goal > 0 ? props.goal : 1;
  const progress = clamp(props.consumed / safeGoal, 0, 1);
  const remainder = Math.max(props.goal - props.consumed, 0);

  return (
    <View style={styles.ringCard}>
      <Svg width={size} height={size}>
        <G rotation={-90} origin={`${size / 2}, ${size / 2}`}>
          <Circle cx={size / 2} cy={size / 2} r={radius} stroke={theme.border} strokeWidth={stroke} fill="transparent" />
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={props.color}
            strokeWidth={stroke}
            fill="transparent"
            strokeDasharray={`${progress * circle} ${circle}`}
            strokeLinecap="round"
          />
        </G>
      </Svg>
      <View style={styles.ringCenter}>
        <Text style={styles.ringLabel}>{props.label}</Text>
        <Text style={styles.ringValue}>{Math.round(props.consumed)}</Text>
        <Text style={styles.ringUnit}>{props.unit}</Text>
      </View>
      <Text style={styles.ringFoot}>restante {Math.max(0, Math.round(remainder))}</Text>
    </View>
  );
}

function MacroDonut({ segments, title }: { segments: Segment[]; title: string }) {
  const size = 180;
  const stroke = 22;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((acc, item) => acc + Math.max(item.value, 0), 0);

  if (total <= 0) {
    return (
      <View style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.helperText}>Sin datos para representar.</Text>
      </View>
    );
  }

  let offset = 0;

  return (
    <View style={styles.sectionCard}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.donutWrap}>
        <Svg width={size} height={size}>
          <G rotation={-90} origin={`${size / 2}, ${size / 2}`}>
            {segments.map((segment) => {
              const ratio = Math.max(segment.value, 0) / total;
              const length = ratio * circumference;
              const circle = (
                <Circle
                  key={segment.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  stroke={segment.color}
                  strokeWidth={stroke}
                  fill="transparent"
                  strokeDasharray={`${length} ${circumference - length}`}
                  strokeDashoffset={-offset}
                />
              );
              offset += length;
              return circle;
            })}
          </G>
        </Svg>
        <View style={styles.donutCenterBox}>
          <Text style={styles.donutCenterTitle}>Macros</Text>
          <Text style={styles.donutCenterSub}>{Math.round(total)} g</Text>
        </View>
      </View>
      <View style={styles.legendWrap}>
        {segments.map((segment) => (
          <View key={segment.label} style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: segment.color }]} />
            <Text style={styles.legendText}>
              {segment.label} {Math.round(segment.value)}g
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function DashboardScreen() {
  const auth = useAuth();
  const [selectedDate, setSelectedDate] = useState(formatDateLocal(new Date()));
  const [monthKey, setMonthKey] = useState(formatMonth(new Date()));
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [calendar, setCalendar] = useState<CalendarDayEntry[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [loadingCalendar, setLoadingCalendar] = useState(true);

  const dayMap = useMemo(() => {
    const map = new Map<number, CalendarDayEntry>();
    calendar.forEach((entry) => {
      const day = Number(entry.date.slice(-2));
      if (Number.isFinite(day)) {
        map.set(day, entry);
      }
    });
    return map;
  }, [calendar]);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const data = await auth.fetchDaySummary(selectedDate);
      setSummary(data);
    } catch (error) {
      Alert.alert("Dashboard", parseApiError(error));
    } finally {
      setLoadingSummary(false);
    }
  }, [auth, selectedDate]);

  const loadCalendar = useCallback(async () => {
    setLoadingCalendar(true);
    try {
      const data = await auth.fetchCalendar(monthKey);
      setCalendar(data.days);
    } catch (error) {
      Alert.alert("Calendario", parseApiError(error));
    } finally {
      setLoadingCalendar(false);
    }
  }, [auth, monthKey]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    void loadCalendar();
  }, [loadCalendar]);

  const segments: Segment[] = [
    { label: "Prote", value: summary?.consumed.protein_g ?? 0, color: "#4fd4ff" },
    { label: "Grasa", value: summary?.consumed.fat_g ?? 0, color: "#f6c453" },
    { label: "Carbs", value: summary?.consumed.carbs_g ?? 0, color: "#61ea9f" },
  ];

  const cells = calendarCells(monthKey);

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.mainScroll}>
        <AppHeader title="Dashboard" subtitle={`Día ${selectedDate}`} />

        <View style={styles.rowWrap}>
          <RingProgress
            label="kcal"
            consumed={summary?.consumed.kcal ?? 0}
            goal={summary?.goal?.kcal_goal ?? Math.max(summary?.consumed.kcal ?? 0, 1)}
            color="#65d9ff"
            unit="kcal"
          />
          <RingProgress
            label="prote"
            consumed={summary?.consumed.protein_g ?? 0}
            goal={summary?.goal?.protein_goal ?? Math.max(summary?.consumed.protein_g ?? 0, 1)}
            color="#50f3c8"
            unit="g"
          />
          <RingProgress
            label="fat"
            consumed={summary?.consumed.fat_g ?? 0}
            goal={summary?.goal?.fat_goal ?? Math.max(summary?.consumed.fat_g ?? 0, 1)}
            color="#ffc97c"
            unit="g"
          />
          <RingProgress
            label="carbs"
            consumed={summary?.consumed.carbs_g ?? 0}
            goal={summary?.goal?.carbs_goal ?? Math.max(summary?.consumed.carbs_g ?? 0, 1)}
            color="#8cb4ff"
            unit="g"
          />
        </View>

        {summary?.goal ? (
          <View style={styles.sectionCard}>
            <Text style={styles.sectionTitle}>Progreso diario</Text>

            {[
              {
                key: "kcal",
                label: "Kcal",
                consumed: summary.consumed.kcal,
                goal: summary.goal.kcal_goal,
                color: "#65d9ff",
              },
              {
                key: "protein",
                label: "Proteína",
                consumed: summary.consumed.protein_g,
                goal: summary.goal.protein_goal,
                color: "#50f3c8",
              },
              {
                key: "fat",
                label: "Grasa",
                consumed: summary.consumed.fat_g,
                goal: summary.goal.fat_goal,
                color: "#ffc97c",
              },
              {
                key: "carbs",
                label: "Carbs",
                consumed: summary.consumed.carbs_g,
                goal: summary.goal.carbs_goal,
                color: "#8cb4ff",
              },
            ].map((metric) => {
              const progress = clamp(metric.consumed / Math.max(metric.goal, 1), 0, 1);
              return (
                <View key={metric.key} style={styles.metricProgressRow}>
                  <View style={styles.metricProgressHeader}>
                    <Text style={styles.metricProgressLabel}>{metric.label}</Text>
                    <Text style={styles.metricProgressValue}>
                      {Math.round(metric.consumed)} / {Math.round(metric.goal)}
                    </Text>
                  </View>
                  <View style={styles.metricProgressTrack}>
                    <View
                      style={[
                        styles.metricProgressFill,
                        {
                          width: `${progress * 100}%`,
                          backgroundColor: metric.color,
                        },
                      ]}
                    />
                  </View>
                </View>
              );
            })}
          </View>
        ) : null}

        <MacroDonut segments={segments} title="Quesito de macros consumidos" />

        <View style={styles.sectionCard}>
          <View style={styles.calendarHeader}>
            <Pressable onPress={() => setMonthKey((current) => moveMonth(current, -1))} style={styles.calendarNavBtn}>
              <Text style={styles.calendarNavText}>{"<"}</Text>
            </Pressable>
            <Text style={styles.sectionTitle}>{monthKey}</Text>
            <Pressable onPress={() => setMonthKey((current) => moveMonth(current, 1))} style={styles.calendarNavBtn}>
              <Text style={styles.calendarNavText}>{">"}</Text>
            </Pressable>
          </View>

          {loadingCalendar ? <ActivityIndicator color={theme.accent} /> : null}

          <View style={styles.weekDaysRow}>
            {["L", "M", "X", "J", "V", "S", "D"].map((label) => (
              <Text key={label} style={styles.weekDayLabel}>
                {label}
              </Text>
            ))}
          </View>

          <View style={styles.calendarGrid}>
            {cells.map((cell, idx) => {
              if (cell === null) {
                return <View key={`empty-${idx}`} style={styles.calendarCellEmpty} />;
              }

              const isoDate = dayFromMonthAndCell(monthKey, cell);
              const active = selectedDate === isoDate;
              const entry = dayMap.get(cell);
              return (
                <Pressable
                  key={isoDate}
                  onPress={() => setSelectedDate(isoDate)}
                  style={[styles.calendarCell, active && styles.calendarCellActive]}
                >
                  <Text style={[styles.calendarCellText, active && styles.calendarCellTextActive]}>{cell}</Text>
                  {entry && entry.intake_count > 0 ? <View style={styles.calendarDot} /> : null}
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionTitleRow}>
            <Text style={styles.sectionTitle}>Registros del día</Text>
            <SecondaryButton title="Recargar" onPress={() => void loadSummary()} />
          </View>

          {loadingSummary ? <ActivityIndicator color={theme.accent} /> : null}

          {!loadingSummary && summary && summary.intakes.length === 0 ? (
            <Text style={styles.helperText}>No hay intakes registrados para este día.</Text>
          ) : null}

          {!loadingSummary && summary
            ? summary.intakes.map((item) => (
                <View key={item.id} style={styles.intakeRow}>
                  <View>
                    <Text style={styles.intakeName}>{item.product_name ?? "Producto"}</Text>
                    <Text style={styles.intakeMeta}>{new Date(item.created_at).toLocaleTimeString()}</Text>
                  </View>
                  <Text style={styles.intakeKcal}>{Math.round(item.nutrients.kcal)} kcal</Text>
                </View>
              ))
            : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function HistoryScreen() {
  const auth = useAuth();
  const [monthKey, setMonthKey] = useState(formatMonth(new Date()));
  const [days, setDays] = useState<CalendarDayEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await auth.fetchCalendar(monthKey);
      setDays(response.days);
    } catch (error) {
      Alert.alert("Historial", parseApiError(error));
    } finally {
      setLoading(false);
    }
  }, [auth, monthKey]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.mainScroll}>
        <AppHeader title="History" subtitle="Resumen mensual de registros" />

        <View style={styles.sectionCard}>
          <View style={styles.calendarHeader}>
            <Pressable onPress={() => setMonthKey((current) => moveMonth(current, -1))} style={styles.calendarNavBtn}>
              <Text style={styles.calendarNavText}>{"<"}</Text>
            </Pressable>
            <Text style={styles.sectionTitle}>{monthKey}</Text>
            <Pressable onPress={() => setMonthKey((current) => moveMonth(current, 1))} style={styles.calendarNavBtn}>
              <Text style={styles.calendarNavText}>{">"}</Text>
            </Pressable>
          </View>

          {loading ? <ActivityIndicator color={theme.accent} /> : null}

          {days.length === 0 && !loading ? <Text style={styles.helperText}>Sin registros en este mes.</Text> : null}

          {days.map((entry) => (
            <View key={entry.date} style={styles.historyRow}>
              <Text style={styles.historyDate}>{entry.date}</Text>
              <Text style={styles.historyValue}>{entry.intake_count} intakes</Text>
              <Text style={styles.historyValue}>{Math.round(entry.kcal)} kcal</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function SettingsScreen() {
  const auth = useAuth();
  const [apiDraft, setApiDraft] = useState(auth.apiBaseUrl);
  const [checking, setChecking] = useState(false);

  const applyApi = async () => {
    const normalized = normalizeBaseUrl(apiDraft);
    if (!normalized) {
      Alert.alert("API", "URL inválida.");
      return;
    }

    auth.setApiBaseUrl(normalized);
    setChecking(true);
    const ok = await auth.checkHealth(normalized);
    setChecking(false);

    if (!ok) {
      Alert.alert("API", "No se pudo conectar con esa URL.");
      return;
    }

    Alert.alert("API", "Conexión OK.");
  };

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.mainScroll}>
        <AppHeader title="Settings" subtitle="Cuenta y red" />

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Cuenta</Text>
          <Text style={styles.helperText}>{auth.user?.email}</Text>
          <Text style={styles.helperText}>email_verified: {String(auth.user?.email_verified ?? false)}</Text>
          <Text style={styles.helperText}>onboarding_completed: {String(auth.user?.onboarding_completed ?? false)}</Text>
          <SecondaryButton title="Cerrar sesión" onPress={() => void auth.logout()} />
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>API base URL</Text>
          <InputField label="URL" value={apiDraft} onChangeText={setApiDraft} autoCapitalize="none" />
          <PrimaryButton title="Guardar y probar" onPress={() => void applyApi()} loading={checking} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function QuantityMethodSelector(props: {
  method: IntakeMethod;
  onChange: (method: IntakeMethod) => void;
  product: Product;
}) {
  const options: Array<{ label: string; value: IntakeMethod; disabled?: boolean }> = [
    { label: "Gramos", value: "grams" },
    { label: "Porción", value: "units", disabled: !props.product.serving_size_g },
    { label: "% paquete", value: "percent_pack", disabled: !props.product.net_weight_g },
  ];

  return (
    <View style={styles.methodRow}>
      {options.map((option) => {
        const active = option.value === props.method;
        return (
          <Pressable
            key={option.value}
            onPress={() => {
              if (!option.disabled) {
                props.onChange(option.value);
              }
            }}
            style={[styles.methodChip, active && styles.methodChipActive, option.disabled && styles.methodChipDisabled]}
          >
            <Text style={[styles.methodChipText, active && styles.methodChipTextActive]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function ScanScreen() {
  const auth = useAuth();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanLocked, setScanLocked] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [phase, setPhase] = useState<"camera" | "label" | "quantity">("camera");
  const [barcode, setBarcode] = useState("");
  const [product, setProduct] = useState<Product | null>(null);
  const [preferredServing, setPreferredServing] = useState<ProductPreference | null>(null);

  const [labelName, setLabelName] = useState("");
  const [labelBrand, setLabelBrand] = useState("");
  const [labelText, setLabelText] = useState("");
  const [labelPhotos, setLabelPhotos] = useState<string[]>([]);
  const [labelQuestions, setLabelQuestions] = useState<string[]>([]);

  const [method, setMethod] = useState<IntakeMethod>("grams");
  const [grams, setGrams] = useState(120);
  const [units, setUnits] = useState(1);
  const [percentPack, setPercentPack] = useState(25);
  const [saving, setSaving] = useState(false);

  const resetToCamera = () => {
    setPhase("camera");
    setScanLocked(false);
    setProcessing(false);
    setProduct(null);
    setPreferredServing(null);
    setLabelName("");
    setLabelBrand("");
    setLabelText("");
    setLabelPhotos([]);
    setLabelQuestions([]);
    setMethod("grams");
    setGrams(120);
    setUnits(1);
    setPercentPack(25);
  };

  const prefillFromPreference = (nextProduct: Product, pref: ProductPreference | null) => {
    if (!pref) {
      if (nextProduct.serving_size_g) {
        setMethod("units");
        setUnits(1);
      } else {
        setMethod("grams");
        setGrams(120);
      }
      return;
    }

    setMethod(pref.method);
    if (pref.quantity_g) {
      setGrams(pref.quantity_g);
    }
    if (pref.quantity_units) {
      setUnits(pref.quantity_units);
    }
    if (pref.percent_pack) {
      setPercentPack(pref.percent_pack);
    }
  };

  const handleScan = async (result: BarcodeScanningResult) => {
    if (scanLocked) {
      return;
    }

    setScanLocked(true);
    setProcessing(true);
    Vibration.vibrate(50);

    try {
      const raw = result.data.trim();
      setBarcode(raw);
      const lookup = await auth.lookupByBarcode(raw);

      if (lookup.product) {
        setProduct(lookup.product);
        prefillFromPreference(lookup.product, lookup.preferred_serving);
        setPreferredServing(lookup.preferred_serving);
        setLabelName(lookup.product.name);
        setLabelBrand(lookup.product.brand ?? "");
        setPhase("quantity");
      } else {
        setProduct(null);
        setPreferredServing(null);
        setLabelName("");
        setLabelBrand("");
        setLabelQuestions([
          lookup.message ?? "No hay nutrición suficiente para este barcode.",
          ...lookup.missing_fields.map((field) => `Falta ${field}`),
        ]);
        setPhase("label");
      }
    } catch (error) {
      Alert.alert("Scan", parseApiError(error));
      setScanLocked(false);
      setPhase("camera");
    } finally {
      setProcessing(false);
    }
  };

  const captureLabelPhoto = async () => {
    const permissionResult = await ImagePicker.requestCameraPermissionsAsync();
    if (!permissionResult.granted) {
      Alert.alert("Permisos", "Necesitas permisos de cámara para capturar etiqueta.");
      return;
    }

    const result = await ImagePicker.launchCameraAsync({ quality: 0.7, allowsEditing: false });
    const firstAsset = result.canceled ? null : result.assets[0];
    if (!firstAsset?.uri) {
      return;
    }

    setLabelPhotos((current) => [...current, firstAsset.uri]);
  };

  const createFromLabel = async () => {
    if (!barcode.trim()) {
      Alert.alert("Barcode", "No hay barcode activo.");
      return;
    }

    if (!labelName.trim()) {
      Alert.alert("Producto", "Indica nombre del producto.");
      return;
    }

    setSaving(true);
    try {
      const response = await auth.createProductFromLabel({
        barcode,
        name: labelName.trim(),
        brand: labelBrand.trim(),
        labelText: labelText.trim(),
        photos: labelPhotos,
      });

      if (!response.created || !response.product) {
        const questions = response.questions.join("\n") || "No se pudo crear el producto.";
        Alert.alert("Etiqueta", questions);
        setLabelQuestions(response.questions);
        return;
      }

      setProduct(response.product);
      prefillFromPreference(response.product, preferredServing);
      setPhase("quantity");
    } catch (error) {
      Alert.alert("Etiqueta", parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  const saveIntake = async () => {
    if (!product) {
      return;
    }

    setSaving(true);
    try {
      if (method === "grams") {
        await auth.createIntake({ product_id: product.id, method: "grams", quantity_g: grams });
      } else if (method === "units") {
        await auth.createIntake({ product_id: product.id, method: "units", quantity_units: units });
      } else {
        await auth.createIntake({ product_id: product.id, method: "percent_pack", percent_pack: percentPack });
      }

      Alert.alert("Consumo", "Intake guardado correctamente.");
      resetToCamera();
    } catch (error) {
      Alert.alert("Consumo", parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  const requestCameraAndUnlock = async () => {
    const granted = permission?.granted ?? false;
    if (granted) {
      return;
    }

    const result = await requestPermission();
    if (!result.granted) {
      Alert.alert("Permisos", "Activa permiso de cámara para escanear.");
    }
  };

  useEffect(() => {
    void requestCameraAndUnlock();
  }, []);

  const hasCamera = permission?.granted ?? false;

  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.scanContainer}>
        <AppHeader title="Scan" subtitle="Solo cámara: centra el barcode dentro del rectángulo" />

        {phase === "camera" ? (
          <View style={styles.scanCameraWrap}>
            {hasCamera ? (
              <CameraView
                style={styles.cameraView}
                onBarcodeScanned={scanLocked ? undefined : handleScan}
                barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e"] }}
              />
            ) : (
              <View style={styles.centered}>
                <Text style={styles.helperText}>Permiso de cámara pendiente.</Text>
                <SecondaryButton title="Conceder permiso" onPress={() => void requestCameraAndUnlock()} />
              </View>
            )}

            <View pointerEvents="none" style={styles.scanOverlay}>
              <View style={styles.scanFrame}>
                <View style={[styles.scanCorner, styles.scanCornerTopLeft]} />
                <View style={[styles.scanCorner, styles.scanCornerTopRight]} />
                <View style={[styles.scanCorner, styles.scanCornerBottomLeft]} />
                <View style={[styles.scanCorner, styles.scanCornerBottomRight]} />
              </View>
              <Text style={styles.scanHint}>Alinea el barcode dentro del marco</Text>
            </View>

            {processing ? (
              <View style={styles.scanBusyOverlay}>
                <ActivityIndicator color={theme.accent} size="large" />
                <Text style={styles.helperText}>Buscando producto...</Text>
              </View>
            ) : null}
          </View>
        ) : null}

        {phase === "label" ? (
          <ScrollView contentContainerStyle={styles.scanPane} keyboardShouldPersistTaps="handled">
            <View style={styles.sectionCard}>
              <Text style={styles.sectionTitle}>Producto no encontrado o incompleto</Text>
              <Text style={styles.helperText}>Barcode detectado: {barcode}</Text>

              {labelQuestions.map((question) => (
                <Text key={question} style={styles.helperText}>
                  - {question}
                </Text>
              ))}

              <InputField label="Nombre" value={labelName} onChangeText={setLabelName} />
              <InputField label="Marca" value={labelBrand} onChangeText={setLabelBrand} />
              <InputField label="Texto etiqueta (opcional)" value={labelText} onChangeText={setLabelText} />

              <SecondaryButton title="Tomar foto de etiqueta" onPress={() => void captureLabelPhoto()} />
              <Text style={styles.helperText}>{labelPhotos.length} foto(s) adjuntas</Text>

              <PrimaryButton title="Crear producto" onPress={() => void createFromLabel()} loading={saving} />
              <SecondaryButton title="Cancelar" onPress={resetToCamera} disabled={saving} />
            </View>
          </ScrollView>
        ) : null}

        {phase === "quantity" && product ? (
          <ScrollView contentContainerStyle={styles.scanPane} keyboardShouldPersistTaps="handled">
            <View style={styles.sectionCard}>
              <Text style={styles.sectionTitle}>{product.name}</Text>
              <Text style={styles.helperText}>Marca: {product.brand ?? "-"}</Text>
              {product.image_url ? (
                <Image source={{ uri: product.image_url }} style={styles.productImage} resizeMode="contain" />
              ) : (
                <View style={styles.productImagePlaceholder}>
                  <Text style={styles.helperText}>Sin foto disponible para este producto</Text>
                </View>
              )}
              <Text style={styles.helperText}>
                {product.kcal} kcal | P {product.protein_g} | G {product.fat_g} | C {product.carbs_g} ({product.nutrition_basis})
              </Text>

              <QuantityMethodSelector method={method} onChange={setMethod} product={product} />

              {method === "grams" ? (
                <View style={styles.sliderWrap}>
                  <Text style={styles.sliderLabel}>{Math.round(grams)} g</Text>
                  <Slider
                    minimumValue={5}
                    maximumValue={500}
                    step={5}
                    value={grams}
                    onValueChange={setGrams}
                    minimumTrackTintColor={theme.accent}
                    maximumTrackTintColor={theme.border}
                    thumbTintColor={theme.accent}
                  />
                </View>
              ) : null}

              {method === "units" ? (
                <View style={styles.sliderWrap}>
                  <Text style={styles.sliderLabel}>{units.toFixed(1)} porciones</Text>
                  <Slider
                    minimumValue={0.25}
                    maximumValue={6}
                    step={0.25}
                    value={units}
                    onValueChange={setUnits}
                    minimumTrackTintColor={theme.accent}
                    maximumTrackTintColor={theme.border}
                    thumbTintColor={theme.accent}
                  />
                  <Text style={styles.helperText}>serving_size_g: {product.serving_size_g ?? "N/A"}</Text>
                </View>
              ) : null}

              {method === "percent_pack" ? (
                <View style={styles.sliderWrap}>
                  <Text style={styles.sliderLabel}>{Math.round(percentPack)}% paquete</Text>
                  <Slider
                    minimumValue={1}
                    maximumValue={100}
                    step={1}
                    value={percentPack}
                    onValueChange={setPercentPack}
                    minimumTrackTintColor={theme.accent}
                    maximumTrackTintColor={theme.border}
                    thumbTintColor={theme.accent}
                  />
                  <Text style={styles.helperText}>net_weight_g: {product.net_weight_g ?? "N/A"}</Text>
                </View>
              ) : null}

              <PrimaryButton title="Guardar consumo" onPress={() => void saveIntake()} loading={saving} />
              <SecondaryButton title="Volver a cámara" onPress={resetToCamera} disabled={saving} />
            </View>
          </ScrollView>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function MainAppTabs() {
  const [tab, setTab] = useState<MainTab>("dashboard");

  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.flex1}>
        {tab === "dashboard" ? <DashboardScreen /> : null}
        {tab === "scan" ? <ScanScreen /> : null}
        {tab === "history" ? <HistoryScreen /> : null}
        {tab === "settings" ? <SettingsScreen /> : null}
      </View>

      <View style={styles.tabBar}>
        {([
          ["dashboard", "Dashboard"],
          ["scan", "Scan"],
          ["history", "History"],
          ["settings", "Settings"],
        ] as Array<[MainTab, string]>).map(([value, label]) => {
          const active = tab === value;
          return (
            <Pressable key={value} onPress={() => setTab(value)} style={[styles.tabItem, active && styles.tabItemActive]}>
              <Text style={[styles.tabText, active && styles.tabTextActive]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

function RootNavigator() {
  const auth = useAuth();

  if (auth.loading) {
    return <LoadingGate />;
  }

  if (!auth.user && !auth.pendingVerificationEmail) {
    return <AuthStack />;
  }

  if ((auth.user && !auth.user.email_verified) || auth.pendingVerificationEmail) {
    return <VerifyEmailOnlyScreen />;
  }

  if (auth.user && auth.user.email_verified && !auth.user.onboarding_completed) {
    return <OnboardingWizard />;
  }

  return <MainAppTabs />;
}

export default function App() {
  return (
    <AuthProvider>
      <StatusBar style="light" />
      <RootNavigator />
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  flex1: { flex: 1 },
  screen: {
    flex: 1,
    backgroundColor: theme.bg,
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  headerWrap: {
    gap: 6,
  },
  headerTitle: {
    color: theme.text,
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  headerSubtitle: {
    color: theme.muted,
    fontSize: 14,
    lineHeight: 20,
  },
  authScroll: {
    padding: 20,
    gap: 14,
  },
  brandCard: {
    borderRadius: 22,
    padding: 22,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.panel,
    gap: 10,
  },
  brandEyebrow: {
    color: theme.accent,
    fontWeight: "700",
    letterSpacing: 2,
    fontSize: 11,
  },
  brandTitle: {
    color: theme.text,
    fontSize: 30,
    fontWeight: "800",
    lineHeight: 34,
  },
  brandText: {
    color: theme.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  fieldWrap: {
    gap: 8,
  },
  fieldLabel: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "600",
  },
  input: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: theme.text,
    backgroundColor: theme.panelSoft,
  },
  primaryButton: {
    backgroundColor: theme.accent,
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButtonText: {
    color: theme.bg,
    fontSize: 15,
    fontWeight: "700",
  },
  secondaryButton: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 14,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.panelSoft,
  },
  secondaryButtonText: {
    color: theme.text,
    fontWeight: "600",
    fontSize: 14,
  },
  disabledButton: {
    opacity: 0.6,
  },
  helperText: {
    color: theme.muted,
    fontSize: 13,
    lineHeight: 19,
  },
  devHint: {
    color: theme.warning,
    fontSize: 12,
    fontWeight: "700",
  },
  chipsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: theme.panelSoft,
  },
  chipActive: {
    borderColor: theme.accent,
    backgroundColor: theme.accentSoft,
  },
  chipText: {
    color: theme.muted,
    fontSize: 12,
    fontWeight: "600",
  },
  chipTextActive: {
    color: theme.text,
  },
  sectionCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.panel,
    padding: 16,
    gap: 12,
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 17,
    fontWeight: "700",
  },
  sectionTitleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  metricCard: {
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.panelSoft,
    borderRadius: 14,
    padding: 12,
    gap: 6,
  },
  metricTitle: {
    color: theme.muted,
    fontSize: 12,
    fontWeight: "600",
  },
  metricValue: {
    color: theme.text,
    fontSize: 24,
    fontWeight: "700",
  },
  metricBadge: {
    fontSize: 13,
    fontWeight: "700",
  },
  bmiTrack: {
    height: 8,
    borderRadius: 999,
    overflow: "hidden",
    flexDirection: "row",
  },
  bmiBand: {
    flex: 1,
  },
  bmiPointer: {
    width: 10,
    height: 10,
    borderRadius: 999,
  },
  recoBox: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    padding: 12,
    backgroundColor: theme.panelSoft,
  },
  recoTitle: {
    color: theme.text,
    fontWeight: "700",
    marginBottom: 6,
  },
  feedbackBox: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.ok,
    padding: 12,
    backgroundColor: "rgba(112,227,159,0.08)",
    gap: 6,
  },
  feedbackBoxWarning: {
    borderColor: theme.warning,
    backgroundColor: "rgba(255,199,120,0.08)",
  },
  feedbackTitle: {
    color: theme.text,
    fontWeight: "700",
  },
  feedbackLine: {
    color: theme.muted,
    fontSize: 13,
    lineHeight: 18,
  },
  mainScroll: {
    padding: 16,
    gap: 14,
    paddingBottom: 90,
  },
  rowWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    justifyContent: "center",
  },
  metricProgressRow: {
    gap: 6,
  },
  metricProgressHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  metricProgressLabel: {
    color: theme.text,
    fontSize: 13,
    fontWeight: "700",
  },
  metricProgressValue: {
    color: theme.muted,
    fontSize: 12,
    fontWeight: "600",
  },
  metricProgressTrack: {
    height: 9,
    borderRadius: 999,
    backgroundColor: theme.panelSoft,
    borderWidth: 1,
    borderColor: theme.border,
    overflow: "hidden",
  },
  metricProgressFill: {
    height: "100%",
    borderRadius: 999,
  },
  ringCard: {
    width: 150,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.panel,
    alignItems: "center",
    paddingVertical: 12,
    gap: 4,
  },
  ringCenter: {
    position: "absolute",
    top: 38,
    alignItems: "center",
    width: "100%",
  },
  ringLabel: {
    color: theme.muted,
    fontSize: 12,
  },
  ringValue: {
    color: theme.text,
    fontSize: 20,
    fontWeight: "700",
  },
  ringUnit: {
    color: theme.muted,
    fontSize: 11,
  },
  ringFoot: {
    color: theme.muted,
    fontSize: 12,
    marginTop: -8,
  },
  donutWrap: {
    alignItems: "center",
    justifyContent: "center",
  },
  donutCenterBox: {
    position: "absolute",
    alignItems: "center",
    justifyContent: "center",
    gap: 3,
  },
  donutCenterTitle: {
    color: theme.muted,
    fontSize: 12,
  },
  donutCenterSub: {
    color: theme.text,
    fontWeight: "700",
    fontSize: 16,
  },
  legendWrap: {
    gap: 6,
  },
  legendItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  legendDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
  },
  legendText: {
    color: theme.muted,
    fontSize: 13,
  },
  calendarHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  calendarNavBtn: {
    width: 34,
    height: 34,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: theme.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.panelSoft,
  },
  calendarNavText: {
    color: theme.text,
    fontWeight: "700",
    fontSize: 16,
  },
  weekDaysRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  weekDayLabel: {
    width: `${100 / 7}%`,
    textAlign: "center",
    color: theme.muted,
    fontSize: 12,
    fontWeight: "600",
  },
  calendarGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  calendarCell: {
    width: "13.2%",
    aspectRatio: 1,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.panelSoft,
  },
  calendarCellActive: {
    borderColor: theme.accent,
    backgroundColor: theme.accentSoft,
  },
  calendarCellText: {
    color: theme.text,
    fontWeight: "600",
    fontSize: 12,
  },
  calendarCellTextActive: {
    color: theme.accent,
  },
  calendarDot: {
    marginTop: 4,
    width: 6,
    height: 6,
    borderRadius: 999,
    backgroundColor: theme.accent,
  },
  calendarCellEmpty: {
    width: "13.2%",
    aspectRatio: 1,
  },
  intakeRow: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    padding: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: theme.panelSoft,
  },
  intakeName: {
    color: theme.text,
    fontWeight: "600",
    fontSize: 14,
  },
  intakeMeta: {
    color: theme.muted,
    fontSize: 12,
  },
  intakeKcal: {
    color: theme.accent,
    fontWeight: "700",
    fontSize: 13,
  },
  historyRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    backgroundColor: theme.panelSoft,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  historyDate: {
    color: theme.text,
    fontWeight: "700",
    fontSize: 13,
  },
  historyValue: {
    color: theme.muted,
    fontSize: 12,
    fontWeight: "600",
  },
  scanContainer: {
    flex: 1,
    padding: 16,
    gap: 12,
  },
  scanCameraWrap: {
    flex: 1,
    borderRadius: 20,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.panel,
  },
  cameraView: {
    flex: 1,
  },
  scanOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  scanFrame: {
    width: "82%",
    height: 160,
    borderWidth: 2,
    borderColor: "rgba(44,240,197,0.95)",
    borderRadius: 16,
    backgroundColor: "rgba(0,0,0,0.12)",
    position: "relative",
  },
  scanCorner: {
    position: "absolute",
    width: 22,
    height: 22,
    borderColor: theme.accent,
  },
  scanCornerTopLeft: {
    top: -2,
    left: -2,
    borderTopWidth: 4,
    borderLeftWidth: 4,
    borderTopLeftRadius: 8,
  },
  scanCornerTopRight: {
    top: -2,
    right: -2,
    borderTopWidth: 4,
    borderRightWidth: 4,
    borderTopRightRadius: 8,
  },
  scanCornerBottomLeft: {
    bottom: -2,
    left: -2,
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    borderBottomLeftRadius: 8,
  },
  scanCornerBottomRight: {
    bottom: -2,
    right: -2,
    borderBottomWidth: 4,
    borderRightWidth: 4,
    borderBottomRightRadius: 8,
  },
  scanHint: {
    marginTop: 12,
    color: theme.text,
    fontWeight: "700",
    fontSize: 12,
    letterSpacing: 0.2,
  },
  scanBusyOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(5,7,13,0.68)",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  scanPane: {
    paddingBottom: 100,
    gap: 12,
  },
  productImage: {
    width: "100%",
    height: 180,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    backgroundColor: "#090d16",
  },
  productImagePlaceholder: {
    width: "100%",
    height: 120,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 12,
    backgroundColor: theme.panelSoft,
    alignItems: "center",
    justifyContent: "center",
    padding: 12,
  },
  methodRow: {
    flexDirection: "row",
    gap: 8,
    flexWrap: "wrap",
  },
  methodChip: {
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: theme.panelSoft,
  },
  methodChipActive: {
    borderColor: theme.accent,
    backgroundColor: theme.accentSoft,
  },
  methodChipDisabled: {
    opacity: 0.45,
  },
  methodChipText: {
    color: theme.muted,
    fontSize: 12,
    fontWeight: "700",
  },
  methodChipTextActive: {
    color: theme.text,
  },
  sliderWrap: {
    gap: 8,
  },
  sliderLabel: {
    color: theme.text,
    fontWeight: "700",
    fontSize: 15,
  },
  tabBar: {
    position: "absolute",
    left: 14,
    right: 14,
    bottom: 12,
    flexDirection: "row",
    backgroundColor: theme.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: theme.border,
    padding: 6,
    gap: 6,
  },
  tabItem: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  tabItemActive: {
    backgroundColor: theme.accentSoft,
  },
  tabText: {
    color: theme.muted,
    fontWeight: "700",
    fontSize: 12,
  },
  tabTextActive: {
    color: theme.accent,
  },
});
