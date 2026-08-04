# Body OS Usable System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans or an equivalent task-by-task execution flow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a usable Body OS loop for `#身体`, `#训练`, `#恢复`, and `#营养` using Garmin-derived context plus minimal manual records.

**Architecture:** Keep Garmin as the sensor layer, keep raw data immutable, and build project decisions from cleaned JSON datasets and runtime context. Add small pure-policy modules for training, recovery, nutrition, and manual training records, then expose them through the existing input parser handler.

**Tech Stack:** Python 3.13, JSON files, unittest, existing input parser handlers, existing Body OS Garmin mapper.

---

## File Structure

- Create `08_工具脚本（Tools）/身体管理/training_log.py`: Parse and store minimal manual training records.
- Create `08_工具脚本（Tools）/身体管理/recovery_policy.py`: Combine energy and training context into recovery guidance.
- Create `08_工具脚本（Tools）/身体管理/nutrition_policy.py`: Produce minimum viable nutrition guidance without a food database.
- Modify `08_工具脚本（Tools）/身体管理/garmin_bodyos_365d.py`: Include recovery and nutrition runtime contexts in dataset and summary.
- Modify `02_执行引擎（Engine）/输入解析引擎/handlers/body_os.py`: Make `#训练`, `#恢复`, `#营养`, and `#身体` directly useful in dry-run and normal modes.
- Modify `02_执行引擎（Engine）/每日排程引擎/daily_scheduler.py`: Add a pure task-adjustment helper for `study_load`.
- Add tests under `tests/` for training log parsing, recovery policy, nutrition policy, Body OS interface, dataset summary, and scheduler task adjustment.

## Tasks

### Task 1: Manual Training Log

- [ ] Write failing tests for parsing strength and running input.
- [ ] Implement `training_log.py` with `parse_training_entry`, `compute_strength_volume`, and `append_training_entry`.
- [ ] Verify tests pass.

### Task 2: Recovery Policy

- [ ] Write failing tests for low body energy, high training warning, and normal recovery.
- [ ] Implement `derive_recovery_policy`.
- [ ] Wire recovery context into Garmin dataset summary.
- [ ] Verify tests pass.

### Task 3: Nutrition Policy

- [ ] Write failing tests for minimum protein guidance and no food database behavior.
- [ ] Implement `derive_nutrition_policy`.
- [ ] Wire nutrition context into Garmin dataset summary.
- [ ] Verify tests pass.

### Task 4: User Interface

- [ ] Write failing tests for `#训练`, `#恢复`, `#营养`, and enriched `#身体`.
- [ ] Update `handlers/body_os.py` so each entry returns actionable guidance.
- [ ] Verify tests pass.

### Task 5: Scheduler Control

- [ ] Write failing tests for `adjust_tasks_for_energy_policy`.
- [ ] Implement L1/L2-safe task adjustment helper without mutating real calendar.
- [ ] Verify scheduler tests pass.

### Task 6: Regenerate Data And Regression

- [ ] Regenerate `body_os_dataset_365d.json`, `body_os_garmin_summary.json`, `body_os_today_energy.json`, and runtime `_energy_status.json` from existing raw.
- [ ] Run Body OS dry-runs.
- [ ] Run root tests and input parser tests.
