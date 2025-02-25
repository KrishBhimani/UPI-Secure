# -*- coding: utf-8 -*-
"""finalise.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1olE5QYCLchsP3spVtNaOiX9_jEqZ-AeL
"""

!pip install keras_tuner
import numpy as np
import pandas as pd
import os
import dask.dataframe as dd
import networkx as nx
import tensorflow as tf
import xgboost as xgb
import joblib
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, MinMaxScaler
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score, confusion_matrix, f1_score
import seaborn as sns
import matplotlib.pyplot as plt
from imblearn.over_sampling import SMOTE
from google.colab import drive
import keras_tuner as kt

# drive.mount('/content/drive', force_remount=True)
file_path = "balanced_dataset3.csv"
df = pd.read_csv(file_path, dtype={'Errors?': 'object'})
df['Merchant State'] = df['Merchant State'].fillna('Unknown')
df['Errors?'] = df['Errors?'].fillna('No Error')
df['DateTime'] = pd.to_datetime(
    df['Year'].astype(str) + '-' + df['Month'].astype(str) + '-' + df['Day'].astype(str) + ' ' + df['Time'].astype(str)
)
df.drop(columns=['Year', 'Month', 'Day', 'Time'], inplace=True)

categorical_cols = ['User', 'Card', 'Merchant Name', 'Merchant City', 'Merchant State', 'Errors?', 'Use Chip','Is Fraud?']
label_encoders = {}
for col in categorical_cols:
    df[col] = df[col].astype(str)
    le = LabelEncoder()
    df[col] = le.fit_transform(df[col])
    label_encoders[col] = le

df['Amount'] = df['Amount'].replace('[\$,]', '', regex=True).astype(float)
df['Hour'] = df["DateTime"].dt.hour
df['DayOfWeek'] = df["DateTime"].dt.dayofweek
df['Month'] = df["DateTime"].dt.month

scaler = MinMaxScaler()
df[['Amount', 'Hour', 'DayOfWeek', 'Month']] = scaler.fit_transform(df[['Amount', 'Hour', 'DayOfWeek', 'Month']])

X = df.drop(columns=['Is Fraud?', 'DateTime'])
y = df['Is Fraud?']

# Handle Missing Values Before SMOTE
X.fillna(X.median(), inplace=True)

# Apply SMOTE to balance fraud cases
smote = SMOTE(sampling_strategy=0.5, random_state=42)
X_resampled, y_resampled = smote.fit_resample(X, y)

X_train, X_test, y_train, y_test = train_test_split(X_resampled, y_resampled, test_size=0.2, random_state=42)

# Reshape for LSTM
X_train_lstm = X_train.values.reshape((X_train.shape[0], 1, X_train.shape[1]))
X_test_lstm = X_test.values.reshape((X_test.shape[0], 1, X_test.shape[1]))

def build_model(hp):
    model = Sequential([
        LSTM(hp.Int('units_1', min_value=64, max_value=256, step=32), return_sequences=True),
        Dropout(hp.Float('dropout_1', 0.2, 0.5, step=0.1)),
        LSTM(hp.Int('units_2', min_value=64, max_value=128, step=32)),
        Dropout(hp.Float('dropout_2', 0.2, 0.5, step=0.1)),
        Dense(hp.Int('dense_units', min_value=32, max_value=128, step=16), activation='relu'),
        Dense(1, activation='sigmoid')
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model

tuner = kt.RandomSearch(build_model, objective='val_accuracy', max_trials=10, executions_per_trial=1, directory='tuner_results')

tuner.search(X_train_lstm, y_train, epochs=15, validation_data=(X_test_lstm, y_test))
best_hps = tuner.get_best_hyperparameters(num_trials=1)[0]
best_model = tuner.hypermodel.build(best_hps)
best_model.fit(X_train_lstm, y_train, epochs=25, batch_size=256, validation_data=(X_test_lstm, y_test))

best_model.save("fraud_detection_lstm.h5")
xgb_model = xgb.XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.05, scale_pos_weight=2, random_state=42)
xgb_model.fit(X_train, y_train)
joblib.dump(xgb_model, "fraud_detection_xgb.pkl")

lstm_model = load_model("fraud_detection_lstm.h5")
xgb_model = joblib.load("fraud_detection_xgb.pkl")

y_pred_lstm = lstm_model.predict(X_test_lstm).flatten()
y_pred_xgb = xgb_model.predict_proba(X_test)[:, 1]

threshold = 0.4  # Adjusted based on validation set AUC-ROC
y_pred_combined = (0.6 * y_pred_xgb + 0.4 * y_pred_lstm) > threshold
y_pred_combined = y_pred_combined.astype(int)

cm = confusion_matrix(y_test, y_pred_combined)
plt.figure(figsize=(6, 5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', xticklabels=['Not Fraud', 'Fraud'], yticklabels=['Not Fraud', 'Fraud'])
plt.xlabel("Predicted Label")
plt.ylabel("True Label")
plt.title("Confusion Matrix for Improved Model")
plt.show()

print("Final Model Performance:")
print("Accuracy:", accuracy_score(y_test, y_pred_combined))
print("F1 Score:", f1_score(y_test, y_pred_combined))
print("ROC AUC:", roc_auc_score(y_test, y_pred_combined))
print(classification_report(y_test, y_pred_combined))