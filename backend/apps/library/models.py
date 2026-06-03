from __future__ import annotations

from django.db import models
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Keyword(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    normalized_name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["normalized_name"]

    def save(self, *args, **kwargs) -> None:
        if not self.normalized_name:
            self.normalized_name = self.name.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class KnowledgeSpace(TimeStampedModel):
    class Kind(models.TextChoices):
        PAPERS = "papers", "Papers"
        DOCS = "docs", "Docs"
        CODE = "code", "Code"
        MIXED = "mixed", "Mixed"

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, allow_unicode=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MIXED)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.SET_NULL,
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True) or self.name.strip().lower().replace(" ", "-")
        super().save(*args, **kwargs)

    def ancestors(self) -> list["KnowledgeSpace"]:
        items: list[KnowledgeSpace] = []
        current = self.parent
        while current is not None:
            items.append(current)
            current = current.parent
        items.reverse()
        return items

    def path_names(self) -> list[str]:
        return [space.name for space in self.ancestors()] + [self.name]

    def path_label(self) -> str:
        return " / ".join(self.path_names())

    def depth(self) -> int:
        return len(self.ancestors())

    def descendant_ids(self) -> list[int]:
        ids: list[int] = []
        stack = list(self.children.filter(is_active=True))
        while stack:
            child = stack.pop()
            ids.append(child.id)
            stack.extend(child.children.filter(is_active=True))
        return ids

    def would_create_cycle(self, new_parent: "KnowledgeSpace | None") -> bool:
        current = new_parent
        while current is not None:
            if current.id == self.id:
                return True
            current = current.parent
        return False

    def __str__(self) -> str:
        return self.name
