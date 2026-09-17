# Written by hand rather than generated, because makemigrations has one
# question about this field and only a person can answer it: the column is
# required and the table may already have rows.
#
# The answer is an empty one-off default. Nothing is deployed, so no contract
# predates REQ-SHARTNOMA-003 in any installation that matters; the default is
# what the migration has to say about a development database rather than a
# state the application can produce, because raise_contract() and the entry
# form both refuse a contract with no document.

import applications.attachments
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0013_contract_entry"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="pdf",
            field=models.FileField(
                default="",
                help_text="PDF, eng ko`pi bilan 10 MB (DEC-019).",
                storage=applications.attachments.attachment_storage,
                upload_to="shartnomalar/%Y/%m",
                validators=[applications.attachments.validate_pdf],
                verbose_name="Shartnoma (PDF)",
            ),
            preserve_default=False,
        ),
    ]
