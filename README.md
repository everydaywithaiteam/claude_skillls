# Claude Code skills

Personal Claude Code skills for the Everyday With AI channel.

| Skill | Purpose |
|---|---|
| `ewai-create-yt-visualizations` | HyperFrames-ready HTML visualizations + 4K b-roll clips |
| `ewai-edit-video` | Edit recordings in Tella, record missing screen/B-roll beats, export |

`ewai-publish-video` lives in the `yt_uploader` repo, next to the code it drives.

## How it's wired

Each skill folder here is symlinked into `~/.claude/skills/` so Claude Code picks it up:

```bash
ln -s ~/Claude/skills/<skill-name> ~/.claude/skills/<skill-name>
```

On a new machine: clone this repo to `~/Claude/skills`, then create the symlinks above.
