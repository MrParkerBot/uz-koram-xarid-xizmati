"""A category may be added without a number, and is given the next one.

Only the column's blank flag and its help text change - a blank field is a
form rule, not a database one, and the number itself is still required and
unique in the table. MahsulotTuri.save() fills it, as a status left unplaced
is given the end of its list.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('xarid', '0019_application_status_back_to_ariza_statuses'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mahsulotturi',
            name='category_number',
            field=models.PositiveIntegerField(blank=True, help_text="Olti xonali kod, bo'lim kategoriyani shu raqam bilan taniydi. Bo'sh qoldirilsa, keyingi raqam avtomatik beriladi.", unique=True, verbose_name='Category Raqami'),
        ),
    ]
