# News Digest Design System

## Visual Theme & Atmosphere
- **Mood**: Clean, editorial, information-dense but breathable
- **Density**: Medium-high - maximize information per screen without overwhelming
- **Design Philosophy**: Notion-inspired minimalism with warm serif headings

## Color Palette & Roles

| Role | Hex | Usage |
|------|-----|-------|
| --bg | #ffffff | Background (light mode) |
| --bg-hover | #f7f6f3 | Hover states |
| --bg-gray | #f1f1ef | Section backgrounds |
| --border | #e9e9e7 | Dividers and borders |
| --text | #37352f | Primary text |
| --text-sec | #6b6b6b | Secondary text |
| --text-light | #9b9a97 | Meta information |
| --accent | #2eaadc | Links and highlights |

## Typography Rules

| Element | Font Family | Size | Weight |
|---------|-------------|------|--------|
| Headings | Georgia, Noto Serif SC | 2.2rem | 700 |
| Body | System UI, -apple-system | 15px | 400 |
| Mono | SF Mono, Consolas | - | - |

## Component Stylings

### Navigation Pills
- Background: Transparent
- Hover: --bg-gray
- Border radius: 4px
- Padding: 4px 10px

### Cards/Rows
- Padding: 8px 12px
- Hover: --bg-hover
- Transition: 200ms ease

### Buttons
- Border radius: 4px
- Padding: 4px 12px
- Hover: Background changes to --bg-hover, text to --accent

## Layout Principles

- **Max width**: 780px
- **Padding**: 48px sides (20px mobile)
- **Spacing**: Consistent 8px grid
- **Section margin**: 40px

## Depth & Elevation

- **Shadow**: 0 1px 3px rgba(0,0,0,0.04)
- **Shadow-lg**: 0 4px 16px rgba(0,0,0,0.06)

## Responsive Behavior

- **Mobile breakpoint**: 840px
- **Touch targets**: Minimum 44px
- **Collapsing**: Nav pills wrap, content adjusts width

## Do's and Don'ts

**Do**:
- Use serif for headings
- Keep information density high but readable
- Use subtle hover states
- Maintain consistent 8px spacing

**Don't**:
- Use bright/neon colors
- Overcrowd with decorative elements
- Use inconsistent spacing
- Make text too small (<13px)
