# ml-models/train_models.py
import pandas as pd
import numpy as np
from prophet import Prophet
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
import joblib
import os

def train_prophet_model(data_path):
    # Cargar datos históricos
    df = pd.read_csv(data_path)
    df['ds'] = pd.to_datetime(df['date'])
    df['y'] = df['rate']
    
    # Entrenar modelo
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=True
    )
    model.fit(df[['ds', 'y']])
    
    # Guardar modelo
    joblib.dump(model, 'prophet_model.pkl')
    
if __name__ == "__main__":
    train_prophet_model('historical_rates.csv')