BOTH: This plugin keeps references at more than one depth, so a guessed `**/{PLUGIN}/*/references/…` shape misses everything under `skills/<name>/`.
SKILLS_ONLY: This plugin's references live under `skills/<name>/`, never at the plugin root, so a guessed `**/{PLUGIN}/*/references/…` shape matches nothing at all.
ROOT_ONLY:
