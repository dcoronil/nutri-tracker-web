# Development Build iOS (Expo Dev Client + EAS)

Este proyecto ya está preparado para dejar Expo Go y trabajar con **Development Build** en iPhone.

## Requisitos

- Cuenta de Expo (`expo.dev`)
- Cuenta Apple Developer (para firmar iOS en dispositivo físico)
- iPhone registrado en Expo/EAS
- Dependencias instaladas en `apps/mobile`

## 1) Login en Expo / EAS

```bash
cd apps/mobile
npx expo login
npx eas login
```

## 2) Registrar tu iPhone

```bash
cd apps/mobile
npx eas device:create
```

Sigue el flujo de QR/perfil para registrar el dispositivo.

## 3) Lanzar build development iOS

```bash
cd apps/mobile
npm run eas:build:ios:dev
```

También puedes usar:

```bash
make ios-dev-build
```

El perfil usado es `development` (`developmentClient: true`, `distribution: internal`).

## 4) Instalar el build en iPhone

- Al terminar el build, EAS te dará un enlace/QR.
- Abre ese enlace en el iPhone e instala la app.
- Si es la primera vez, acepta certificados/perfiles cuando iOS lo pida.

## 5) Arrancar bundler para dev client

```bash
cd apps/mobile
npm run devclient:start
```

o:

```bash
make mobile-devclient
```

## 6) Abrir app en iPhone

- Abre la app instalada (Development Build), no Expo Go.
- La app cargará el bundle del Metro que acabas de arrancar.

## Scripts disponibles

En `apps/mobile/package.json`:

- `devclient:start`
- `eas:build:ios:dev`
- `eas:build:ios:preview`
- `eas:submit:ios` (preparado para futuro)

## Troubleshooting rápido

- **No conecta al bundler**
  - iPhone y ordenador deben estar en la misma WiFi.
  - Prueba: `npx expo start --dev-client -c`.

- **Error de firma / certificados**
  - Repite `npx eas device:create`.
  - Reintenta `npm run eas:build:ios:dev`.

- **Cambia el bundle identifier**
  - Actualiza `ios.bundleIdentifier` en `apps/mobile/app.json`.
  - Vuelve a generar build iOS (la firma/provisioning se recalcula).

- **App abre pero pantalla en blanco**
  - Reinicia Metro con caché limpia: `npx expo start --dev-client -c`.
  - Verifica que la API esté levantada y `EXPO_PUBLIC_API_BASE_URL` sea correcta.
