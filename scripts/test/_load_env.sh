#!/usr/bin/env bash
# Safely load a .env file into the environment WITHOUT running it as a script.
# Handles inline comments (KEY=val  # note), blank/comment lines, optional
# surrounding quotes, and `export KEY=` prefixes. Does NOT do variable
# expansion or command substitution (so `$(...)`, spaces, etc. can't break it).
#
# Usage:  source scripts/test/_load_env.sh [path-to-.env]
load_env() {
  local file="${1:-.env}"
  [[ -f "$file" ]] || { echo "load_env: no $file (skipping)"; return 0; }
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"      # ltrim
    [[ -z "$line" || "$line" == \#* ]] && continue
    line="${line#export }"
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    # strip an inline comment: " #..." or tab+#... (only when # is preceded by space)
    val="${val%%[[:space:]]#*}"
    # trim surrounding whitespace
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    # strip matching surrounding quotes
    if [[ "$val" == \"*\" || "$val" == \'*\' ]]; then
      val="${val:1:${#val}-2}"
    fi
    # key must be a valid shell identifier
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$key=$val"
  done < "$file"
}
