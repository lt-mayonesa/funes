# funes

## Always run ./scripts/check.sh before commiting

## Git

 - When starting new work, always work in a new branch from main and push to a new PR unless specified otherwise.
 - work in small atomic commits
 - use conventional commits format
    ```
    <type>[optional scope]: <description>
    
    [optional body]
    
    [optional footer(s)]
    ```

## Workflow

 - Keep track in [TODO.md](docs/design/TODO.md) as you work. Only **add** items if approved by a human.
 - Whenever adding a feature, fix, or breaking change bump the version in meson.build accordingly.
 - Any future functionality that needs to be ported to Wayland should be tracked in [WAYLAND.md](docs/design/WAYLAND.md).