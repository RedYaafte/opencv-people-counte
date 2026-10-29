# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

FastAPI backend with a plain HTML/CSS/JavaScript interface, OpenCV video processing, and SQLite event storage. The user selected a local-first version.

## Users

The project owner runs the app locally to analyze uploaded footage or a browser camera. Portfolio viewers may inspect the code and a future recorded demonstration.

## Product Purpose

Count and inspect people entering and leaving across a configurable line. Show the annotated feed, current totals, and historical progress in one interface.

## Operating Context

The user selects a local video or grants browser camera access, sets line orientation and position, starts analysis, and reviews a session's events and chart. The existing command-line workflow remains available.

## Capabilities and Constraints

- Preserve the existing HOG detector and centroid tracker for the first web version.
- Record sessions and crossing events in SQLite.
- Support uploaded videos and live browser camera analysis.
- Show entries, exits, and cumulative occupancy; occupancy starts at zero and is calculated as entries minus exits, so it may be negative if people already present leave first.
- The first web version runs on the user's computer; public deployment, authentication, and multi-user operation are outside the confirmed scope.
- Interface and README copy are in English; the existing video overlay uses Spanish direction labels.

## Evidence on Hand

The repository contains a working command-line counter, tracking tests, and local generated media excluded from Git. No public demo footage or verified accuracy benchmark is provided.

## Product Principles

- Keep source, configuration, progress, and result visible in the same workflow.
- Make counting direction explicit before analysis begins.
- Treat each analysis as a separate, reviewable session.
- Show measured data without implying detection accuracy has been validated.
