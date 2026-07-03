"""Field validators for the signup form.

CONVENTION (follow this for any new validator):
- Each validator is a plain function `validate_<field>(value: str) -> None`.
- On failure it raises `ValidationError(field=..., message=...)`.
- Register the validator in the `VALIDATORS` dict at the bottom of this file so
  the form runner picks it up automatically. Do NOT call validators directly
  from the form runner; it iterates `VALIDATORS`.
"""

from __future__ import annotations


class ValidationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def validate_email(value: str) -> None:
    if "@" not in value or "." not in value.split("@")[-1]:
        raise ValidationError(field="email", message="Enter a valid email address.")


def validate_username(value: str) -> None:
    if not value:
        raise ValidationError(field="username", message="Username is required.")
    if len(value) < 3:
        raise ValidationError(
            field="username", message="Username must be at least 3 characters."
        )


# The form runner iterates this registry. Add new validators here.
VALIDATORS = {
    "email": validate_email,
    "username": validate_username,
}
