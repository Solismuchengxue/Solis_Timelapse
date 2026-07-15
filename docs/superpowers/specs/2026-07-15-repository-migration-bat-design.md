# Solis_Timelapse Repository Migration BAT Design

## Goal

Provide one root-level Windows BAT file that moves the complete repository from `F:\02_Tools\sony_timelapse` to `F:\01_Project\Solis_Timelapse` after Codex releases the old directory, while preserving access for existing Codex tasks that still reference the old path.

## User Flow

1. The user double-clicks `migrate_to_new_path.bat` from the current repository.
2. The launcher copies an embedded helper BAT to `%TEMP%`, starts it in a separate command window, and exits so the source script cannot hold the repository open.
3. The helper explains that Codex must be closed, then waits and retries the move for a bounded period.
4. After the move succeeds, the helper verifies that the target contains `.git` and that Git resolves the target as the repository root.
5. The helper creates a directory junction at the old path pointing to the new path.
6. The helper reports the new project path and tells the user to reopen `F:\01_Project\Solis_Timelapse` in Codex.

## Safety Rules

- Source and target paths are fixed constants; command-line path overrides are not supported.
- Abort before moving when the source is missing, the destination already exists, or `F:\01_Project` is missing.
- Never copy files and then delete the source. Use a same-volume directory move so the repository, ignored local data, Git metadata, and virtual environment remain one unit.
- Never edit, copy, or delete `C:\Users\smile\.codex`, its session files, memory files, JSON state, or SQLite databases.
- Create the compatibility junction only after the move and Git validation succeed.
- If Git validation fails after the move, do not create the junction and report the exact recovery paths. Do not automatically delete or reverse user data.
- Refuse to replace any unexpected file or directory that appears at the old path before junction creation.

## Codex Continuity

Codex conversations and memories remain in the user-global `C:\Users\smile\.codex` directory and therefore are unaffected by moving the repository. Existing tasks can continue resolving their recorded old workspace path through the junction. New tasks should open the canonical path `F:\01_Project\Solis_Timelapse` directly.

The script does not promise to rewrite the workspace assignment of an already-open Codex task. That task must be closed before Windows releases the source directory, and the new canonical project path must be opened after migration.

## Files

- Add `migrate_to_new_path.bat` at the repository root.
- Add a static contract test that checks fixed paths, temporary helper execution, bounded retry behavior, Git validation, junction creation, and the absence of commands that modify `.codex` data.
- Add a short migration section to `README.md` describing when to run the script and how to reopen the project.

## Verification

- Static tests verify the safety contract without moving the real repository.
- A temporary-directory harness exercises the helper's move, Git-root verification, and junction behavior using disposable directories on the same drive when Windows permissions allow junction creation.
- The real migration is run only by the user after reviewing the script and closing Codex.
