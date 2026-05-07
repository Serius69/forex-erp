from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0002_alter_prediction_options_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='EnsembleWeightHistory',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency_pair', models.CharField(db_index=True, max_length=10)),
                ('weights',       models.JSONField()),
                ('recorded_at',   models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'ordering': ['-recorded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='ensembleweighthistory',
            index=models.Index(fields=['currency_pair', '-recorded_at'], name='pred_ewh_pair_date_idx'),
        ),
        migrations.AlterField(
            model_name='predictionmodel',
            name='model_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('PROPHET',  'Prophet'),
                    ('LSTM',     'LSTM (legacy)'),
                    ('BILSTM',   'BiLSTM + Attention'),
                    ('XGBOOST',  'XGBoost'),
                    ('ARIMA',    'Auto-ARIMA'),
                    ('ENSEMBLE', 'Ensemble'),
                ],
            ),
        ),
    ]
