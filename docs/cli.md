# Command line

`pip install "tplx[cli,jinja]"` adds the `tplx` command (also `python -m tplx`).
Without the `cli` extra the command exits naming the extra.

```bash
tplx render templates/boot.cfg.j2 -s hostname=web01      # one file
tplx render boot.cfg -r templates -d host.json -o boot.cfg  # a name, data from JSON
tplx render web01.boot.cfg boot.cfg -r templates         # the first name found
tplx find boot.cfg -r templates                          # which file, which engine
tplx engines                                             # what is registered
tplx render nginx.conf -r templates --env -u debug       # envsubst from the environment
```

```text
tplx [--version]
tplx render NAME... [-r ROOT]... [-p PATH]... [-u MODE] [--env] [-d FILE|-] [-s KEY=VALUE]... [-o FILE|-]
tplx find NAME... [-r ROOT]... [-p PATH]... [--json]     (alias: which)
tplx engines [--json]
```

- `NAME` is looked up in the roots; several names are tried in order and the
  first found wins. With no `-r`, a single `NAME` that is an existing file is
  that file, its directory the root.
- `-r/--root` (repeat; default `templates`), `-p/--path` (repeat; searched
  first, relative ones inside each root), `-u/--undefined` (`strict`,
  `lenient`, `debug`).
- `render`: `--env` starts the data from the environment variables;
  `-d/--data` a JSON object file or `-` for standard input over it;
  `-s/--set key=value` over it (repeat; `a.b=v` nests and merges into
  `--data`; a value `json:...` is JSON); `-o/--output` a file or `-`. Output
  is written as bytes, unchanged.
- `find` prints `<origin>\t<Engine>`, or `{"origin", "engine"}` with `--json`.
- `engines` prints `<Engine>\t<suffixes>\t<priority>` per engine, highest
  priority first, or a JSON array with `--json`.
- `render` and `find` also take `-v`/`-q` and `--loglevel [NAME:]LEVEL`.

Exit status: `0` done, `1` the operation failed (no such template, an engine
error, a file that cannot be read or written), `2` a usage error. A failure
prints `tplx: error: <message>` on standard error.
