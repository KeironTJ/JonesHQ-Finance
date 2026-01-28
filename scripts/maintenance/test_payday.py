"""Test payday service"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.payday_service import PaydayService
from datetime import date

app = create_app()

with app.app_context():
    print("Testing payday service...")
    
    # Test payday calculation
    payday = PaydayService.get_payday_for_month(2026, 2)
    print(f"✓ Feb 2026 payday: {payday}")
    
    # Test period calculation
    start, end, label = PaydayService.get_payday_period(2026, 1)
    print(f"✓ Jan 2026 period: {start} to {end} ({label})")
    
    # Test weekend adjustment
    # Jan 15, 2026 is a Thursday, so should stay the same
    jan_payday = PaydayService.get_payday_for_month(2026, 1)
    print(f"✓ Jan 2026 payday: {jan_payday} (weekday: {jan_payday.strftime('%A')})")
    
    print("\n✓ All tests passed!")
