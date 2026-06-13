"""Generate a bcrypt password hash for a Lead Scraper user.

Operator tool, used during client onboarding (see RUNBOOK). Prints a hash to
paste into the ``password`` field of an ``[auth.users.*]`` block in that
client's secrets file. The plaintext password is never stored or echoed.

Usage:
    python gen_password_hash.py            # prompts for the password (hidden)
    python gen_password_hash.py "pw"       # hash a password given as an argument

Prefer the interactive prompt: a password passed as an argument can be captured
in your shell history.
"""

import getpass
import sys

import bcrypt


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def main() -> int:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Password to hash: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1

    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1

    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
