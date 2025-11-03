<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
-->

# Shared Color Mode Implementation

## Overview

The ColorModeProvider and color mode functionality have been centralized in the `@helios/shared` package, allowing all apps in the Helios workspace to share the same color mode state and toggle functionality.

## What Changed

### 1. **Moved to Shared Library** (`@helios/shared`)

Created in `shared/src/context/`:

- **`ColorModeProvider.tsx`**: Wraps `next-themes` ThemeProvider
- **`useColorMode.tsx`**: Hook for accessing color mode with a `toggleColorMode()` function

### 2. **Enhanced HeliosButton**

Added new `colorModeToggle` variant to `shared/src/components/HeliosButton.tsx`:

```tsx
<HeliosButton variant="colorModeToggle" />
// Automatically shows sun/moon icon and toggles color mode on click
```

**Features:**
- Automatically displays sun (☀️) or moon (🌙) icon based on current theme
- Handles click to toggle between light/dark mode
- Optional children to customize the text
- Uses the shared `useColorMode` hook

### 3. **Updated Both Apps**

**Environment Manager** (`environment-manager/src/`):
- ✅ Uses shared `ColorModeProvider` from `@helios/shared`
- ✅ HomePage uses `<HeliosButton variant="colorModeToggle" />`
- ✅ Removed local `colorMode` context imports

**Alerts** (`alerts/src/`):
- ✅ Uses shared `ColorModeProvider` from `@helios/shared`
- ✅ AlertsPage uses `<HeliosButton variant="colorModeToggle" />`

## Usage

### Basic Usage

```tsx
import { ColorModeProvider, HeliosButton } from "@helios/shared";

export const App = () => (
  <ChakraProvider value={system}>
    <ColorModeProvider>
      {/* Color mode toggle button */}
      <HeliosButton variant="colorModeToggle" />
      
      {/* Your app content */}
      <YourContent />
    </ColorModeProvider>
  </ChakraProvider>
);
```

### Custom Toggle Button

```tsx
import { HeliosButton } from "@helios/shared";

// Default: Shows icon + "Toggle Light/Dark Mode"
<HeliosButton variant="colorModeToggle" />

// Custom text
<HeliosButton variant="colorModeToggle">
  Switch Theme
</HeliosButton>

// With size
<HeliosButton variant="colorModeToggle" size="lg" />
```

### Programmatic Control

```tsx
import { useColorMode } from "@helios/shared";

const MyComponent = () => {
  const { colorMode, toggleColorMode, setColorMode } = useColorMode();
  
  return (
    <div>
      <p>Current mode: {colorMode}</p>
      <button onClick={toggleColorMode}>Toggle</button>
      <button onClick={() => setColorMode("dark")}>Force Dark</button>
      <button onClick={() => setColorMode("light")}>Force Light</button>
    </div>
  );
};
```

## Button Variants

The `HeliosButton` now supports 4 variants:

| Variant | Description | Usage |
|---------|-------------|-------|
| `primary` | Blue button (default) | `<HeliosButton variant="primary">` |
| `secondary` | Gray button | `<HeliosButton variant="secondary">` |
| `danger` | Red button | `<HeliosButton variant="danger">` |
| `colorModeToggle` | Color mode toggle with icon | `<HeliosButton variant="colorModeToggle" />` |

## Benefits

1. **Shared State**: Color mode preference is synchronized across both apps
2. **DRY Principle**: No duplicate color mode logic in each app
3. **Consistent UX**: Same toggle behavior and appearance everywhere
4. **Easy to Extend**: Add new apps that automatically inherit color mode functionality

## Installation

After pulling these changes:

```bash
cd /Users/brent/dev/airflow/files/plugins/Helios
pnpm install
pnpm build
```

## Files Modified

### Created:
- `shared/src/context/ColorModeProvider.tsx`
- `shared/src/context/useColorMode.tsx`

### Updated:
- `shared/src/components/HeliosButton.tsx` - Added `colorModeToggle` variant
- `shared/src/index.ts` - Export color mode functionality
- `shared/package.json` - Added `next-themes` and `react-icons` peer dependencies
- `environment-manager/src/main.tsx` - Use shared ColorModeProvider
- `environment-manager/src/pages/HomePage.tsx` - Use colorModeToggle button
- `alerts/src/main.tsx` - Use shared ColorModeProvider
- `alerts/src/pages/AlertsPage.tsx` - Use colorModeToggle button

## Notes

- The `next-themes` package provides theme persistence (saves to localStorage)
- Color mode is automatically applied via CSS classes on the HTML element
- Both apps can be on different pages but share the same color mode preference
- The toggle button automatically shows the correct icon (sun for dark mode → light, moon for light mode → dark)

