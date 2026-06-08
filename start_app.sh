#!/bin/bash
cd ~/Desktop/stock_sentiment

echo "Updating articles and analysis..."
python3 run_pipeline.py --mock --analysis-limit 1000

echo "Starting Streamlit app..."
streamlit run web/app.py

