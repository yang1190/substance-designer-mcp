"""Zip every skills/<name>/ folder into skills/packages/<name>.skill (a zip with <name>/SKILL.md)."""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
OUT = os.path.join(SKILLS, "packages")


def skill_dirs():
    for name in sorted(os.listdir(SKILLS)):
        if os.path.isfile(os.path.join(SKILLS, name, "SKILL.md")):
            yield name


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in skill_dirs():
        dst = os.path.join(OUT, name + ".skill")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            base = os.path.join(SKILLS, name)
            for dirpath, _, files in os.walk(base):
                for f in sorted(files):
                    full = os.path.join(dirpath, f)
                    z.write(full, os.path.join(name, os.path.relpath(full, base)).replace(os.sep, "/"))
        print("wrote", os.path.relpath(dst, ROOT))


if __name__ == "__main__":
    main()
