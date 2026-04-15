# Changelog

## [Unreleased]

### Added
- Add configurable ultrasonic automation rules with persisted threshold, delay, cooldown, enable state, and action selection.
- Add backend-triggered automation actions for stopping the motor, homing the arm, or starting a saved workflow.
- Add a live sensor telemetry and automation management UI for creating, editing, and monitoring ultrasonic trigger rules.

### Changed
- Redesign the control dashboard to separate live telemetry, automation rules, workflow management, and manual motion controls more clearly.

### Fixed
- Fix duplicate serial-port contention from the Flask debug reloader by starting background sensor monitoring only once.
