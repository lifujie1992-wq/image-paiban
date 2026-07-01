---
project: PSB Template Workbench
register: product
aesthetic_direction: technical / utilitarian
color_strategy: restrained
design_system: bespoke
design_variance: 4
motion_intensity: 2
visual_density: 7
---

## Design Read

一个面向重复生产的图版工作台：安静、清楚、密度高，把注意力留给模板画布和图片位操作。

## Signature

左侧是分段任务面板，右侧是网格化画布工作区。选中、已放入、编辑中的图片位使用明确的描边状态，减少猜测。

## Color

| role | hex | use |
| --- | --- | --- |
| background | `#eef1f4` | app shell and canvas workspace |
| surface | `#f9fafb` | toolbar and panel surroundings |
| panel | `#ffffff` | sidebar panels, modal, menus |
| text | `#192026` | primary UI text |
| muted | `#65717d` | secondary labels |
| line | `#d7dee5` | dividers and borders |
| accent | `#0f766e` | primary action, selected asset, assigned image position |
| warning | `#b45309` | edit mode and active image position |
| danger | `#b42318` | destructive actions |

## Type

Use the existing Windows Chinese UI stack: `Microsoft YaHei`, `Segoe UI`, `Arial`, sans-serif. Keep headings compact and use font weight, spacing, and color instead of oversized text.

## Scales

Spacing uses 4px increments. Radius scale is 5px, 8px, 10px. Motion is limited to short 120-140ms state changes and must honor `prefers-reduced-motion`.

## Voice

Plain production-tool copy. The user-facing term is “图片位”. Internal code may keep `slot` and `hotspot` until a later refactor.

Every screen must read as the same product if placed side by side.
