"""Shared abstract model.

Lives here rather than in core/models.py so accounts can import it without
pulling in the whole core model graph.
"""

from django.db import models


class BaseModel(models.Model):
    """Creation and modification timestamps for every model in the project.

    Two things to know about these fields, both of which have bitten before:

    `created_at` is auto_now_add, so it is stamped once on insert and **cannot
    be overridden** — passing a value is silently ignored, not an error.
    Backdating imported rows needs a second UPDATE after insert.

    `updated_at` is auto_now, which means it only moves when *this row* is
    saved. It does not notice changes to related objects — adding a
    registration does not touch its project. And Django only applies it when
    the field is listed in `save(update_fields=[...])`, so every such call
    must include "updated_at" or the timestamp goes stale with no error.

    Deliberately not applied to `User`: AbstractUser already has date_joined,
    and two fields meaning the same thing drift apart the moment one is
    written without the other.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
