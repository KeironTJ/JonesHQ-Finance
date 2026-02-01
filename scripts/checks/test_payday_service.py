"""Test PaydayService.get_period_for_date"""
import sys
from pathlib import Path
from datetime import date

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from services.payday_service import PaydayService

app = create_app()

with app.app_context():
    test_dates = [
        date(2026, 2, 1),
        date(2026, 7, 19),
        date(2026, 1, 31),
    ]
    
    print("\nTesting PaydayService.get_period_for_date():\n")
    
    for test_date in test_dates:
        period = PaydayService.get_period_for_date(test_date)
        print(f"Date: {test_date} → Period: {period}")
    
    print("\n")
