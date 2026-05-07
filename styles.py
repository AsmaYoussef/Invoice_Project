CUSTOM_CSS = """
<style>
    /* Main Layout */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 4rem;
    }
    
    /* Header Cards */
    .info-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 20px;
        margin-bottom: 25px;
    }
    .metric-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        border-radius: 12px;
        padding: 20px;
        border-left: 6px solid #2563eb;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        transition: transform 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .addr-card { 
        grid-column: span 2; 
        border-left-color: #10b981; 
    }
    .metric-label { 
        font-size: 0.8em; 
        color: #6b7280; 
        margin-bottom: 6px; 
        font-weight: 700; 
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value { 
        font-size: 1.1em; 
        color: #111827; 
        font-weight: 600; 
        word-break: break-word;
    }
    .empty-val { 
        color: #d1d5db; 
        font-style: italic; 
        font-weight: normal;
    }

    /* Custom Dataframe Styling */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #e5e7eb;
    }
    
    /* Section Titles */
    h3 {
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 10px;
        margin-top: 20px;
    }
</style>
"""