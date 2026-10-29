# Web dashboard design

The dashboard is an operating surface for a local video analysis session. The annotated feed is the primary evidence; configuration sits beside it, and the event chart and history sit below it.

## Visual system

- Cool blue-gray page surface (`#e9f0f2`), near-white panels (`#fbfdfe`), and dark ink (`#172b34`) give the video viewport clear visual priority.
- Teal (`#16816f`) marks entries, red (`#bc4d42`) marks exits, and blue (`#4d62a7`) marks occupancy in both metrics and chart.
- Georgia provides editorial headings; Cantarell with system fallbacks provides compact interface text. Data values use tabular numerals.
- Panels use borders and restrained radii. The live status dot is the only continuous animation and respects reduced-motion preferences.

## Layout and behavior

- Desktop: source/configuration rail beside the monitor, followed by a full-width chart and event/history columns.
- Narrow screens: configuration, monitor, chart, events, and history stack in task order.
- Upload and camera modes share line controls. Direction copy changes with line orientation so the entry side is explicit before analysis.
- Idle, queued, running, completed, and failed states each have visible status; controls are disabled while a session runs.
- The chart is derived from stored crossing events. The table presents the same events for inspection without relying on color alone.
