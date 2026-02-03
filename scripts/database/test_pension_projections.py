"""
Quick test to generate projections for all pensions
This will create projection data through retirement for all active pensions
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.pension_service import PensionService
from models.pensions import Pension


def test_projections():
    """Test projection generation"""
    app = create_app()
    with app.app_context():
        print("\n=== Pension Projection Test ===\n")
        
        # Get all active pensions
        pensions = Pension.query.filter_by(is_active=True).all()
        
        if not pensions:
            print("⚠ No active pensions found. Add some pensions first.")
            return
        
        print(f"Found {len(pensions)} active pension(s):\n")
        for p in pensions:
            print(f"  - {p.provider} ({p.person}): £{p.current_value:,.2f}")
        
        print("\nGenerating projections for all scenarios...")
        
        # Generate for each scenario
        for scenario in ['default', 'optimistic', 'pessimistic']:
            print(f"\n{scenario.upper()} scenario:")
            count = PensionService.regenerate_all_projections(scenario=scenario)
            print(f"  ✓ Generated {count} projection records")
        
        # Get retirement summary
        print("\n=== Retirement Summary ===")
        summary = PensionService.get_retirement_summary()
        
        print(f"\nCurrent Total Value: £{summary['total_current_value']:,.2f}")
        print(f"Projected @ Retirement: £{summary['total_projected_value']:,.2f}")
        print(f"Estimated Annual Income: £{summary['total_annual_income']:,.2f}")
        print(f"  - Pension Annuity: £{summary['total_annuity']:,.2f}")
        print(f"  - Government Pension: £{summary['government_pension']:,.2f}")
        print(f"Monthly Income: £{summary['total_monthly_income']:,.2f}")
        
        print("\n✓ Test complete! View at http://127.0.0.1:5000/pensions/projections")


if __name__ == '__main__':
    test_projections()
