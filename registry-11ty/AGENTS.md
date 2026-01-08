# Agent Guidelines for Airflow Registry 11ty

This document contains rules, patterns, and guidelines for working on the Airflow Registry 11ty project.

## Project Overview

## Core Principles


### 0. Minimal JavaScript

- Keep JavaScript to minimum necessary
- Theme toggle only
- No frameworks (no React, Vue, etc.)
- Progressive enhancement approach

## 1. Quality Standards

- **Zero visual regression**: 11ty must match Astro pixel-perfect
- **Semantic HTML**: Use proper elements and structure
- **Maintainable CSS**: Descriptive class names, leverage cascade
- **Light/Dark mode**: Full support with smooth transitions
- **Responsive**: Mobile-first, works on all screen sizes

### 2. Semantic CSS

Follow the principles from https://css-tricks.com/semantic-class-names/:

- **Class names describe CONTENT, not visual appearance**
  - Good: `.hero`, `.badge`, `.provider`
  - Bad: `.blue-text`, `.flex-container`, `.mb-4`

- **Use CSS cascade instead of duplicative prefixes**
  - Good: `.hero .badge`, `.hero h1`, `.hero .search`
  - Bad: `.hero-badge`, `.hero-title`, `.hero-search`
  - Rationale: A hero-badge only makes sense inside a hero section, so the prefix is redundant

- **Leverage semantic HTML5 elements**
  - Use `<section>`, `<header>`, `<nav>`, `<dl>`, `<dt>`, `<dd>`, `<article>`, etc.
  - Example: Stats should use `<dl>` (definition list) not `<div class="stats-grid">`

#### 2.1 No Utility Classes

- Remove ALL utility classes like:
  - Spacing: `.mb-2`, `.py-12`, `.gap-4`, `.px-6`
  - Layout: `.flex`, `.grid`, `.grid-cols-2`, `.items-center`
  - Text: `.text-center`, `.text-lg`, `.font-bold`
- Style elements contextually where they appear
- Use semantic CSS with cascade pattern

#### 2.1 Contextual Button Styling

- NO `.btn`, `.btn-primary`, `.btn-secondary` classes
- Style buttons contextually:
  ```css
  .hero .popular-providers a {
    /* Styles here */
  }
  ```

## CSS Architecture

### File Structure

```
src/css/
├── tokens.css          # Design tokens (colors, spacing, fonts)
├── main.css            # Main styles with imports
└── base/
    ├── reset.css       # CSS reset
    └── typography.css  # Base typography
```

### Semantic Section Pattern

Each major section follows this pattern:

```css
/* Section container */
.section-name {
  padding: var(--space-20) 0;
  background: /* dark mode background */;
}

html.light .section-name {
  background: /* light mode background */;
}

/* Nested elements using cascade */
.section-name header {
  /* Header styles */
}

.section-name h2 {
  /* Title styles */
}

.section-name .some-element {
  /* Element styles */
}

html.light .section-name .some-element {
  /* Light mode overrides */
}
```

### Design Tokens

Use CSS custom properties defined in `tokens.css`:

- Colors: `--color-navy-900`, `--color-cyan-400`, `--color-gray-700`, etc.
- Spacing: `--space-4` (1rem), `--space-8` (2rem), etc.
- Typography: `--text-base`, `--text-lg`, `--font-semibold`, etc.
- Theme variables: `--bg-primary`, `--text-primary`, `--border-primary`

**IMPORTANT**: Always use CSS custom properties instead of hardcoded color values:
- ✅ Good: `border: 1px solid var(--color-gray-700);`
- ❌ Bad: `border: 1px solid #334155;`

Exceptions: Light mode overrides may use hardcoded colors when they don't have a corresponding token.

### Light/Dark Mode

- Default theme is dark mode
- Light mode uses `.light` class on `<html>` element
- Always provide light mode overrides:
  ```css
  .element {
    background: var(--color-navy-800);
    color: var(--text-primary);
  }

  html.light .element {
    background: #ffffff;
    color: #0f172a;
  }
  ```

## Color Matching

When porting from Astro to 11ty:

1. **Don't guess colors** - read the Astro source files
2. Compare screenshots side-by-side
3. Use exact color values from Astro version
4. Common light mode colors:
   - Hero background: Light cyan/blue gradient
   - Search input: `#ffffff` with `#cbd5e1` border
   - Buttons: `#f1f5f9` background, `#e2e8f0` border
   - Section backgrounds: `#f8fafc` for light gray sections

## Screenshot Testing with shot-scraper

### Installation & Usage

```bash
uvx shot-scraper shot <url> --width 1280 --height 2400 -o <output>.png
uvx shot-scraper multi <config.yaml>
```

### Screenshot Directories

```
screenshots/
├── baseline/        # Astro version (baseline)
│   ├── astro-full-page-dark.png
│   └── astro-full-page-light.png
└── 11ty/           # 11ty version (comparison)
    ├── 11ty-full-page-dark.png
    └── 11ty-full-page-light.png
```

### Light Mode Screenshots

Light mode requires JavaScript to set theme and proper delay:

```yaml
- url: http://localhost:8080
  output: 11ty/11ty-full-page-light.png
  width: 1280
  height: 2400
  javascript: |
    new Promise(takeShot => {
      document.documentElement.classList.remove('dark');
      document.documentElement.classList.add('light');
      setTimeout(() => {
        takeShot();
      }, 1000);
    });
```

**Important**: The Promise pattern with `takeShot()` callback is required. The `wait` parameter doesn't work with JavaScript execution.

### Astro React Theme Toggle

For Astro (React-based), use:

```yaml
javascript: |
  new Promise(takeShot => {
    localStorage.setItem('theme', 'light');
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
    setTimeout(() => {
      takeShot();
    }, 1000);
  });
```

## HTML Structure Examples

## Development Workflow

### Port Checklist

When porting a section from Astro to 11ty:

1. **Read Astro source** - don't guess the structure or colors
2. **Create semantic HTML** with proper elements
3. **Write semantic CSS** using cascade pattern
4. **Add light mode styles** for all elements
5. **Take screenshots** to compare
6. **Iterate** until visual parity achieved

### Common Issues

- **Dark header in light mode**: Check `.site-header` has `html.light` override
- **Section staying dark**: Add `html.light .section-name { background: #f8fafc; }`
- **Wrong border colors**: Check color tokens are indigo not gray
- **Screenshot timing**: Use Promise pattern with 1000ms delay

## CSS Deletion Guidelines

When removing non-semantic CSS:

1. **Search for usage first**: Use grep to find where classes are used
2. **Confirm removal**: If only in CSS and not in refactored templates, delete it
3. **Test visually**: Take screenshots before and after
4. **Common deletions**:
   - Grid/flex utilities: `.grid`, `.flex`, `.items-center`, etc.
   - Spacing utilities: `.mb-*`, `.py-*`, `.gap-*`, etc.
   - Button classes: `.btn`, `.btn-primary`, etc.
   - Text utilities: `.text-center`, `.text-lg`, etc.

## Quality Standards

- **Zero visual regression**: 11ty must match Astro pixel-perfect
- **Semantic HTML**: Use proper elements and structure
- **Maintainable CSS**: Descriptive class names, leverage cascade
- **Light/Dark mode**: Full support with smooth transitions (except during screenshots)
- **Responsive**: Mobile-first, works on all screen sizes

## Reference Files

Key files to reference:
- `/Users/ash/code/airflow/airflow-private/registry-11ty/src/index.njk` - Main template
- `/Users/ash/code/airflow/airflow-private/registry-11ty/src/css/main.css` - Main styles
- `/Users/ash/code/airflow/airflow-private/registry-11ty/src/css/tokens.css` - Design tokens
- `/Users/ash/code/airflow/airflow-private/registry/src/` - Astro baseline for comparison

## Server Ports

- Astro: http://localhost:4321
- 11ty: http://localhost:8080

## Troubleshooting

### Screenshots show different things than browser

This is a timing issue with shot-scraper:
1. CSS transitions may be interfering - temporarily remove them
2. Increase delay in Promise timeout
3. Ensure wait happens AFTER class changes, not before

### Can't find where a class is used

```bash
# Search in templates
grep -r "class-name" src/

# Search in CSS
grep "\.class-name" src/css/
```

### Colors don't match

1. Read the Astro source component
2. Use browser DevTools to inspect computed styles
3. Check both light and dark mode
4. Verify color tokens in `tokens.css`
