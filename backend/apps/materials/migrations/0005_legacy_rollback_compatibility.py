from django.db import migrations


# Preserve the external route's 0003 verbatim. Database defaults also permit
# older application code to insert rows without knowing these new fields.
FORWARD = """
ALTER TABLE materials_material ALTER COLUMN source_kind SET DEFAULT 'unclassified';
ALTER TABLE materials_material ALTER COLUMN external_agent_access SET DEFAULT 'blocked';
DO $$
DECLARE constraint_name text;
BEGIN
    SELECT conname INTO STRICT constraint_name FROM pg_constraint
    WHERE conrelid = 'materials_legacypaperlink'::regclass
      AND confrelid = 'papers_paper'::regclass AND contype = 'f';
    EXECUTE format('ALTER TABLE materials_legacypaperlink DROP CONSTRAINT %I', constraint_name);
    EXECUTE format('ALTER TABLE materials_legacypaperlink ADD CONSTRAINT %I FOREIGN KEY (paper_id) REFERENCES papers_paper(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED', constraint_name);
END $$;
"""
REVERSE = """
ALTER TABLE materials_material ALTER COLUMN source_kind DROP DEFAULT;
ALTER TABLE materials_material ALTER COLUMN external_agent_access DROP DEFAULT;
DO $$
DECLARE constraint_name text;
BEGIN
    SELECT conname INTO STRICT constraint_name FROM pg_constraint
    WHERE conrelid = 'materials_legacypaperlink'::regclass
      AND confrelid = 'papers_paper'::regclass AND contype = 'f';
    EXECUTE format('ALTER TABLE materials_legacypaperlink DROP CONSTRAINT %I', constraint_name);
    EXECUTE format('ALTER TABLE materials_legacypaperlink ADD CONSTRAINT %I FOREIGN KEY (paper_id) REFERENCES papers_paper(id) DEFERRABLE INITIALLY DEFERRED', constraint_name);
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [('materials', '0004_legacy_paper_link')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
