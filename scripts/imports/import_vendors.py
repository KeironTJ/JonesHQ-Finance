"""
Import vendors from curated list
Run this script to populate the vendors table with real merchant data
"""
import sys
import os

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Vendor, Category

# Curated vendor list with types and default categories
VENDORS = [
    # Grocery Stores
    {"name": "Tesco", "type": "Grocery", "category": "Groceries"},
    {"name": "Asda", "type": "Grocery", "category": "Groceries"},
    {"name": "Aldi", "type": "Grocery", "category": "Groceries"},
    {"name": "Lidl", "type": "Grocery", "category": "Groceries"},
    {"name": "Morrisons", "type": "Grocery", "category": "Groceries"},
    {"name": "Sainsburys", "type": "Grocery", "category": "Groceries"},
    {"name": "Co-op", "type": "Grocery", "category": "Groceries"},
    {"name": "Iceland", "type": "Grocery", "category": "Groceries"},
    {"name": "Farmfoods", "type": "Grocery", "category": "Groceries"},
    {"name": "Food Warehouse", "type": "Grocery", "category": "Groceries"},
    {"name": "Marks and Spencers", "type": "Grocery", "category": "Groceries"},
    
    # Fuel & Petrol
    {"name": "Fuel Station", "type": "Fuel", "category": "Fuel"},
    {"name": "Esso", "type": "Fuel", "category": "Fuel"},
    {"name": "BP Rivington North", "type": "Fuel", "category": "Fuel"},
    {"name": "Esso Stoke", "type": "Fuel", "category": "Fuel"},
    
    # Utilities
    {"name": "Severn Trent Water", "type": "Utility", "category": "Water"},
    {"name": "Octopus Energy", "type": "Utility", "category": "Electricity"},
    {"name": "EE", "type": "Utility", "category": "Mobile Phone"},
    {"name": "Sky", "type": "Utility", "category": "Sky"},
    {"name": "Microsoft - One Drive", "type": "Utility", "category": "Cloud Storage"},
    
    # Insurance
    {"name": "Quote Me Happy", "type": "Insurance", "category": "Car Insurance"},
    {"name": "1st Central", "type": "Insurance", "category": "Car Insurance"},
    {"name": "Animal Friends", "type": "Insurance", "category": "Pet Insurance"},
    {"name": "Zurich Insurance", "type": "Insurance", "category": "Insurance"},
    {"name": "LV", "type": "Insurance", "category": "Insurance"},
    {"name": "Dial Direct", "type": "Insurance", "category": "Car Insurance"},
    {"name": "Aviva", "type": "Insurance", "category": "Insurance"},
    
    # Restaurants & Takeaways
    {"name": "McDonalds", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Dominoes", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Just Eat", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Greggs", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Costa", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Nandos", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Wetherspoons", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Brewers Fayre", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Oriental Villa", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Chester Green Fish Bar", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Tuckers Fish Bar", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Harbour Bar", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Cookhouse Pub", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Mundy Arms", "type": "Restaurant", "category": "Eating Out"},
    {"name": "The Newdigate", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Loungers", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Yangtze Derby", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Jolly Asian", "type": "Restaurant", "category": "Eating Out"},
    {"name": "The Kitchen", "type": "Restaurant", "category": "Eating Out"},
    {"name": "Uber Eats", "type": "Restaurant", "category": "Eating Out"},
    
    # Retail Stores
    {"name": "Home Bargains", "type": "Retail", "category": "Household Items"},
    {"name": "B&M", "type": "Retail", "category": "Household Items"},
    {"name": "The Range", "type": "Retail", "category": "Household Items"},
    {"name": "Primark", "type": "Retail", "category": "Clothing"},
    {"name": "Poundland", "type": "Retail", "category": "Household Items"},
    {"name": "Card Factory", "type": "Retail", "category": "Gifts"},
    {"name": "Barnardos", "type": "Retail", "category": "Charity"},
    {"name": "Pets at Home", "type": "Retail", "category": "Pet Food"},
    {"name": "Decathlon", "type": "Retail", "category": "Clothing"},
    {"name": "IKEA", "type": "Retail", "category": "Furniture"},
    {"name": "B&Q", "type": "Retail", "category": "DIY"},
    {"name": "Boyes", "type": "Retail", "category": "Household Items"},
    {"name": "Argos", "type": "Retail", "category": "General"},
    {"name": "The Works", "type": "Retail", "category": "Stationery"},
    {"name": "WH Smith", "type": "Retail", "category": "Stationery"},
    {"name": "The Card Shop", "type": "Retail", "category": "Gifts"},
    {"name": "Hotel Chocolat", "type": "Retail", "category": "Gifts"},
    {"name": "MenKind", "type": "Retail", "category": "Gifts"},
    {"name": "Halfords", "type": "Retail", "category": "Car Parts"},
    {"name": "Shoezone", "type": "Retail", "category": "Clothing"},
    {"name": "Screwfix", "type": "Retail", "category": "DIY"},
    {"name": "Sports Direct", "type": "Retail", "category": "Clothing"},
    {"name": "Specsavers", "type": "Retail", "category": "Opticians"},
    {"name": "Post Office", "type": "Retail", "category": "General"},
    {"name": "Little Eaton Garden Centre", "type": "Retail", "category": "Garden"},
    {"name": "Boots", "type": "Retail", "category": "Pharmacy"},
    {"name": "British Heart Foundation", "type": "Retail", "category": "Charity"},
    {"name": "Bonmarche", "type": "Retail", "category": "Clothing"},
    {"name": "Smiggle", "type": "Retail", "category": "Stationery"},
    {"name": "Dunelm", "type": "Retail", "category": "Household Items"},
    {"name": "Next", "type": "Retail", "category": "Clothing"},
    {"name": "Yours Clothing", "type": "Retail", "category": "Clothing"},
    {"name": "The Perfume Shop", "type": "Retail", "category": "Gifts"},
    {"name": "One Below", "type": "Retail", "category": "Household Items"},
    {"name": "H&M", "type": "Retail", "category": "Clothing"},
    {"name": "Poyntons", "type": "Retail", "category": "Butchers"},
    {"name": "The Entertainer", "type": "Retail", "category": "Toys"},
    {"name": "Cards Direct", "type": "Retail", "category": "Gifts"},
    {"name": "Vinted", "type": "Retail", "category": "Clothing"},
    
    # Online Retailers
    {"name": "Amazon", "type": "Online Retailer", "category": "Amazon"},
    {"name": "Amazon Prime", "type": "Online Retailer", "category": "Amazon Prime"},
    {"name": "SHEIN", "type": "Online Retailer", "category": "Clothing"},
    {"name": "Ebay", "type": "Online Retailer", "category": "General"},
    {"name": "Groupon", "type": "Online Retailer", "category": "Gifts"},
    
    # Entertainment & Subscriptions
    {"name": "Spotify - Family", "type": "Entertainment", "category": "Spotify"},
    {"name": "Disney Plus", "type": "Entertainment", "category": "Disney Plus"},
    {"name": "Xbox Game Pass", "type": "Entertainment", "category": "Xbox Live"},
    {"name": "Minecraft Realms", "type": "Entertainment", "category": "Xbox Live"},
    {"name": "Google Play", "type": "Entertainment", "category": "Google Play"},
    {"name": "Apple", "type": "Entertainment", "category": "Apple"},
    {"name": "TV Licensing", "type": "Entertainment", "category": "TV License"},
    {"name": "Netflix", "type": "Entertainment", "category": "Netflix"},
    
    # Schools & Education
    {"name": "Highfield Hall Primary School", "type": "Education", "category": "School Dinners"},
    {"name": "Langley Mill Academy", "type": "Education", "category": "School Dinners"},
    {"name": "Landau Forte College", "type": "Education", "category": "School Dinners"},
    {"name": "Langley Mill Infants & Juniors", "type": "Education", "category": "School Dinners"},
    {"name": "Parent Pay", "type": "Education", "category": "School Dinners"},
    
    # Childcare & Activities
    {"name": "Emily Grace Dance School", "type": "Childcare", "category": "Dance Classes"},
    {"name": "Child Minder", "type": "Childcare", "category": "Childcare"},
    {"name": "Swimming", "type": "Childcare", "category": "Swimming"},
    {"name": "Swimming Lessons", "type": "Childcare", "category": "Swimming"},
    {"name": "Dinky Dinos", "type": "Childcare", "category": "Childcare"},
    {"name": "Little Princess Parties", "type": "Childcare", "category": "Birthday Parties"},
    
    # Council & Government
    {"name": "Derbyshire County Council", "type": "Government", "category": "Council Tax"},
    {"name": "Amber Valley Council", "type": "Government", "category": "Council Tax"},
    {"name": "Erewash Borough Council", "type": "Government", "category": "Council Tax"},
    {"name": "TFL - ULEZ", "type": "Government", "category": "Fines"},
    {"name": "Civil Enforcement", "type": "Government", "category": "Fines"},
    
    # Health & Fitness
    {"name": "Gym Membership", "type": "Health", "category": "Gym Membership"},
    {"name": "Slimming World", "type": "Health", "category": "Slimming World"},
    {"name": "Rowlands Pharmacy", "type": "Health", "category": "Pharmacy"},
    {"name": "Dentist", "type": "Health", "category": "Dentist"},
    {"name": "Opticians", "type": "Health", "category": "Opticians"},
    {"name": "Peak Pharmacy", "type": "Health", "category": "Pharmacy"},
    {"name": "Derby Royal Hospital", "type": "Health", "category": "Healthcare"},
    {"name": "Royal Derby Hospital", "type": "Health", "category": "Healthcare"},
    {"name": "Infinite Wellbeing", "type": "Health", "category": "Healthcare"},
    {"name": "Heanor Leisure Centre", "type": "Health", "category": "Gym Membership"},
    {"name": "William Gregg Leisure Centre", "type": "Health", "category": "Gym Membership"},
    
    # Services
    {"name": "Haircut", "type": "Services", "category": "Haircut"},
    {"name": "Gould Barbers", "type": "Services", "category": "Haircut"},
    {"name": "Harpers Hairdresser", "type": "Services", "category": "Haircut"},
    {"name": "Barbers", "type": "Services", "category": "Haircut"},
    {"name": "Lucky Haircut", "type": "Services", "category": "Haircut"},
    {"name": "John Parry Barber", "type": "Services", "category": "Haircut"},
    {"name": "Jolly Barber", "type": "Services", "category": "Haircut"},
    {"name": "Mutley Cuts", "type": "Services", "category": "Pet Grooming"},
    {"name": "Lucky Grooming", "type": "Services", "category": "Pet Grooming"},
    {"name": "Car Wash", "type": "Services", "category": "Car Wash"},
    {"name": "Langley Mill Car Wash", "type": "Services", "category": "Car Wash"},
    {"name": "Arc Car Wash", "type": "Services", "category": "Car Wash"},
    {"name": "Window Cleaner", "type": "Services", "category": "Window Cleaning"},
    {"name": "Heanor Phone Repairs", "type": "Services", "category": "Phone Repairs"},
    {"name": "CheckMyFile", "type": "Services", "category": "Credit Report"},
    {"name": "Qustodio", "type": "Services", "category": "Parental Control"},
    
    # Entertainment Venues
    {"name": "Wheelgate", "type": "Entertainment", "category": "Days Out"},
    {"name": "REEL Cinema", "type": "Entertainment", "category": "Cinema"},
    {"name": "Cinema", "type": "Entertainment", "category": "Cinema"},
    {"name": "Showcase Derby Cinema", "type": "Entertainment", "category": "Cinema"},
    {"name": "Treetops Activity Centre", "type": "Entertainment", "category": "Days Out"},
    {"name": "Treetops", "type": "Entertainment", "category": "Days Out"},
    {"name": "WFA Bowl Birthday Party", "type": "Entertainment", "category": "Birthday Parties"},
    {"name": "MFA Bowling", "type": "Entertainment", "category": "Days Out"},
    {"name": "Carsington Water", "type": "Entertainment", "category": "Days Out"},
    {"name": "Royal British Legions Belper", "type": "Entertainment", "category": "Days Out"},
    {"name": "Barefeet Lodge (Ripley Park)", "type": "Entertainment", "category": "Days Out"},
    {"name": "The National Memorial", "type": "Entertainment", "category": "Days Out"},
    {"name": "National Trust", "type": "Entertainment", "category": "Days Out"},
    {"name": "Alton Tower", "type": "Entertainment", "category": "Days Out"},
    {"name": "Theatre Royal Concert Hall", "type": "Entertainment", "category": "Theatre"},
    {"name": "UOD Theatre", "type": "Entertainment", "category": "Theatre"},
    {"name": "Derby Live", "type": "Entertainment", "category": "Theatre"},
    {"name": "Twinlakes Park", "type": "Entertainment", "category": "Days Out"},
    
    # Furniture & Home
    {"name": "Belfield Furnishings", "type": "Furniture", "category": "Furniture"},
    {"name": "Tetrad Furniture", "type": "Furniture", "category": "Furniture"},
    {"name": "Kitchen Design Studios", "type": "Furniture", "category": "Kitchen"},
    {"name": "Seamless Windows", "type": "Furniture", "category": "Windows"},
    {"name": "Andrew Revill Glazing LTD", "type": "Furniture", "category": "Windows"},
    {"name": "Loft Company", "type": "Furniture", "category": "Loft"},
    
    # Parking
    {"name": "Parking", "type": "Transport", "category": "Parking"},
    {"name": "JustPark", "type": "Transport", "category": "Parking"},
    {"name": "Derbion Car Park", "type": "Transport", "category": "Parking"},
    {"name": "Citipark", "type": "Transport", "category": "Parking"},
    
    # Misc
    {"name": "Too Good To Go", "type": "Other", "category": "Groceries"},
    {"name": "Selecta UK", "type": "Other", "category": "Vending"},
    {"name": "PoundStretcher", "type": "Retail", "category": "Household Items"},
    {"name": "Costcutter", "type": "Grocery", "category": "Groceries"},
    {"name": "T J Morris", "type": "Retail", "category": "Household Items"},
    {"name": "The Mencap Society", "type": "Charity", "category": "Charity"},
    {"name": "Bernardos", "type": "Charity", "category": "Charity"},
]


def import_vendors():
    """Import vendors into database"""
    app = create_app()
    
    with app.app_context():
        print("Starting vendor import...")
        print(f"Total vendors to import: {len(VENDORS)}")
        print()
        
        # Get categories for mapping
        categories = {cat.sub_budget: cat for cat in Category.query.all()}
        
        added = 0
        skipped = 0
        errors = 0
        
        for vendor_data in VENDORS:
            try:
                # Check if vendor already exists
                existing = Vendor.query.filter_by(name=vendor_data['name']).first()
                
                if existing:
                    print(f"⏭️  Skipped: {vendor_data['name']} (already exists)")
                    skipped += 1
                    continue
                
                # Find default category
                default_category = None
                if vendor_data.get('category'):
                    default_category = categories.get(vendor_data['category'])
                    if not default_category:
                        print(f"⚠️  Warning: Category '{vendor_data['category']}' not found for {vendor_data['name']}")
                
                # Create vendor
                vendor = Vendor(
                    name=vendor_data['name'],
                    vendor_type=vendor_data.get('type'),
                    default_category_id=default_category.id if default_category else None,
                    is_active=True
                )
                
                db.session.add(vendor)
                print(f"✅ Added: {vendor_data['name']} ({vendor_data['type']})")
                added += 1
                
            except Exception as e:
                print(f"❌ Error adding {vendor_data['name']}: {str(e)}")
                errors += 1
        
        # Commit all changes
        try:
            db.session.commit()
            print()
            print("="*60)
            print("Import Complete!")
            print(f"✅ Added: {added}")
            print(f"⏭️  Skipped: {skipped}")
            print(f"❌ Errors: {errors}")
            print(f"📊 Total vendors in database: {Vendor.query.count()}")
            print("="*60)
        except Exception as e:
            db.session.rollback()
            print(f"❌ Failed to commit: {str(e)}")


if __name__ == '__main__':
    import_vendors()
