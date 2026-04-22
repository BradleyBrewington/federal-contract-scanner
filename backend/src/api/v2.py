"""
Platform API v2
---------------
Serves the React frontend. Handles feed scoring and AI card summaries.

Auth model: React authenticates via Supabase Auth and passes the JWT in the
Authorization header. We decode it to get the user_id, then use the service
key to query Supabase (bypassing RLS is fine here — we enforce company_id
scoping manually).

Direct CRUD that doesn't need server logic (swipes, pipeline, profile edits)
goes React → Supabase directly, so this API stays small.
"""

import os
import re
import json
import random
import base64
import logging
import threading
import requests as http_requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=False)

@app.after_request
def ensure_cors(response):
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Headers", "Authorization, Content-Type")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    return response

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SAM_API_KEY = os.getenv("SAM_API_KEY")

# Notice types that represent actionable procurement opportunities.
# Award notices, J&As, modifications, etc. are filtered out of the feed.
ACTIONABLE_NOTICE_TYPES = [
    "solicitation", "presolicitation", "combined",
    "sources_sought", "special",
]

# Static lookup tables — human-readable labels for codes shown on cards.
NAICS_TITLES = {
    # Construction
    "236110": "Residential Building Construction",
    "236115": "New Single-Family Home Construction",
    "236118": "Residential Remodelers",
    "236210": "Industrial Building Construction",
    "236220": "Commercial Building Construction",
    "237110": "Water & Sewer Line Construction",
    "237120": "Oil & Gas Pipeline Construction",
    "237130": "Power & Communication Line Construction",
    "237210": "Land Subdivision",
    "237310": "Highway & Bridge Construction",
    "237990": "Heavy Civil Engineering Construction",
    "238110": "Foundation & Structure Contractors",
    "238120": "Structural Steel & Precast Concrete",
    "238130": "Framing Contractors",
    "238140": "Masonry Contractors",
    "238150": "Glass & Glazing Contractors",
    "238160": "Roofing Contractors",
    "238170": "Siding Contractors",
    "238190": "Other Building Exterior Contractors",
    "238210": "Electrical Contractors",
    "238220": "Plumbing, Heating & AC Contractors",
    "238290": "Other Building Equipment Contractors",
    "238310": "Drywall & Insulation Contractors",
    "238320": "Painting & Wall Covering Contractors",
    "238330": "Flooring Contractors",
    "238340": "Tile & Terrazzo Contractors",
    "238350": "Finish Carpentry Contractors",
    "238390": "Other Building Finishing Contractors",
    "238910": "Site Preparation Contractors",
    "238990": "Other Specialty Trade Contractors",
    # Food & Chemicals
    "311119": "Other Animal Food Manufacturing",
    "311999": "Food Manufacturing",
    "312111": "Soft Drink Manufacturing",
    "325110": "Petrochemical Manufacturing",
    "325180": "Other Basic Inorganic Chemical Mfg",
    "325199": "Other Basic Organic Chemical Mfg",
    "325412": "Pharmaceutical Preparation Mfg",
    "325413": "In-Vitro Diagnostic Substance Mfg",
    "325414": "Biological Product Manufacturing",
    "325510": "Paint & Coating Manufacturing",
    "325611": "Soap & Detergent Manufacturing",
    "325620": "Toilet Preparation Manufacturing",
    "325910": "Printing Ink Manufacturing",
    "325920": "Explosives Manufacturing",
    "325998": "Chemical Manufacturing",
    # Plastics & Rubber
    "326111": "Plastics Packaging Materials",
    "326199": "Other Plastics Product Manufacturing",
    "326211": "Tire Manufacturing",
    "326290": "Rubber Product Manufacturing",
    # Non-metallic Minerals
    "327110": "Pottery & Ceramics",
    "327215": "Glass Product Manufacturing",
    "327310": "Cement Manufacturing",
    "327410": "Lime Manufacturing",
    "327910": "Abrasive Product Manufacturing",
    "327999": "Non-metallic Mineral Products",
    # Primary Metals
    "331110": "Iron & Steel Mills",
    "331210": "Iron & Steel Pipe & Tube",
    "331315": "Aluminum Sheet & Plate",
    "331410": "Nonferrous Metal Smelting",
    "331510": "Ferrous Metal Foundries",
    "331529": "Nonferrous Metal Foundries",
    # Fabricated Metal
    "332111": "Iron & Steel Forging",
    "332116": "Metal Stamping",
    "332117": "Powder Metallurgy",
    "332119": "Metal Crown & Closure Mfg",
    "332310": "Prefabricated Metal Building Mfg",
    "332321": "Metal Window & Door Mfg",
    "332410": "Power Boiler & Heat Exchanger Mfg",
    "332420": "Metal Tank Manufacturing",
    "332431": "Metal Can Manufacturing",
    "332510": "Hardware Manufacturing",
    "332613": "Spring Manufacturing",
    "332710": "Machine Shops",
    "332721": "Precision Turned Product Mfg",
    "332722": "Bolt & Screw Manufacturing",
    "332811": "Metal Heat Treating",
    "332812": "Metal Coating & Allied Services",
    "332813": "Electroplating & Polishing",
    "332911": "Industrial Valve Manufacturing",
    "332912": "Fluid Power Valve & Fitting Mfg",
    "332913": "Plumbing Fixture Fitting Mfg",
    "332919": "Other Metal Valve & Pipe Fitting",
    "332991": "Ball & Roller Bearing Manufacturing",
    "332992": "Small Arms Ammunition Manufacturing",
    "332993": "Ammunition Manufacturing",
    "332994": "Small Arms & Ordnance Manufacturing",
    "332999": "Fabricated Metal Products",
    # Machinery
    "333120": "Construction Machinery Manufacturing",
    "333131": "Mining Machinery Manufacturing",
    "333241": "Food Product Machinery Mfg",
    "333244": "Printing Machinery Manufacturing",
    "333249": "Industrial Machinery Manufacturing",
    "333310": "Commercial & Service Industry Machinery",
    "333413": "Industrial Fan & Blower Manufacturing",
    "333414": "Heating Equipment Manufacturing",
    "333415": "Air-Conditioning & Heat Pump Equipment",
    "333511": "Industrial Mold Manufacturing",
    "333514": "Special Die & Tool Manufacturing",
    "333515": "Cutting Tool & Machine Tool Accessory",
    "333517": "Machine Tool Manufacturing",
    "333611": "Turbine & Turbine Generator Manufacturing",
    "333612": "Speed Changer & Drive Manufacturing",
    "333613": "Mechanical Power Transmission Equipment",
    "333618": "Engine & Engine Parts Manufacturing",
    "333912": "Air & Gas Compressor Manufacturing",
    "333914": "Measuring & Dispensing Pump Mfg",
    "333921": "Elevator & Moving Stairway Mfg",
    "333922": "Conveyor & Conveying Equipment Mfg",
    "333923": "Overhead Traveling Crane & Hoist Mfg",
    "333924": "Industrial Truck & Tractor Mfg",
    "333991": "Power-Driven Hand Tool Manufacturing",
    "333993": "Packaging Machinery Manufacturing",
    "333994": "Industrial Process Furnace & Oven Mfg",
    "333995": "Fluid Power Cylinder & Actuator Mfg",
    "333996": "Fluid Power Pump & Motor Mfg",
    "333997": "Scale & Balance Manufacturing",
    "333999": "General Purpose Machinery",
    # Computer & Electronics
    "334111": "Electronic Computer Manufacturing",
    "334112": "Computer Storage Device Manufacturing",
    "334118": "Computer Peripheral Equipment Mfg",
    "334210": "Telephone Apparatus Manufacturing",
    "334220": "Radio & TV Broadcasting Equipment",
    "334290": "Other Communications Equipment",
    "334310": "Audio & Video Equipment Manufacturing",
    "334412": "Bare Printed Circuit Board Manufacturing",
    "334413": "Semiconductor & Related Device Mfg",
    "334416": "Capacitor & Resistor Manufacturing",
    "334417": "Electronic Coil & Transformer Mfg",
    "334418": "Printed Circuit Assembly Manufacturing",
    "334419": "Other Electronic Component Mfg",
    "334510": "Electromedical Equipment Manufacturing",
    "334511": "Navigation & Guidance Instruments",
    "334512": "Automatic Environmental Control Mfg",
    "334513": "Industrial Process Variable Instruments",
    "334514": "Totalizing Fluid Meter Manufacturing",
    "334515": "Electricity Measuring Instruments",
    "334516": "Analytical Laboratory Instruments",
    "334517": "Irradiation Apparatus Manufacturing",
    "334519": "Other Measuring Instruments",
    "334610": "Manufacturing & Reproducing Magnetic Media",
    # Electrical Equipment
    "335110": "Electric Lamp Bulb & Part Mfg",
    "335121": "Residential Luminaires Manufacturing",
    "335122": "Commercial Luminaires Manufacturing",
    "335129": "Other Lighting Equipment Manufacturing",
    "335210": "Small Electrical Appliance Manufacturing",
    "335220": "Major Household Appliance Manufacturing",
    "335311": "Power, Distribution & Specialty Transformer",
    "335312": "Motor & Generator Manufacturing",
    "335313": "Switchgear & Switchboard Apparatus Mfg",
    "335314": "Relay & Industrial Control Manufacturing",
    "335911": "Storage Battery Manufacturing",
    "335912": "Primary Battery Manufacturing",
    "335921": "Fiber Optic Cable Manufacturing",
    "335929": "Other Communication & Energy Wire",
    "335931": "Current-Carrying Wiring Device Mfg",
    "335932": "Noncurrent-Carrying Wiring Device Mfg",
    "335991": "Carbon & Graphite Product Manufacturing",
    "335999": "Electronic & Electrical Equipment",
    # Transportation Equipment
    "336110": "Automobile & Light Truck Manufacturing",
    "336120": "Heavy Duty Truck Manufacturing",
    "336211": "Motor Vehicle Body Manufacturing",
    "336212": "Truck Trailer Manufacturing",
    "336213": "Motor Home Manufacturing",
    "336214": "Travel Trailer & Camper Manufacturing",
    "336310": "Motor Vehicle Gasoline Engine Mfg",
    "336320": "Motor Vehicle Electrical Equipment",
    "336330": "Motor Vehicle Steering & Suspension",
    "336340": "Motor Vehicle Brake System Parts",
    "336350": "Motor Vehicle Transmission Parts",
    "336360": "Motor Vehicle Seating & Interior",
    "336370": "Motor Vehicle Metal Stamping",
    "336390": "Other Motor Vehicle Parts Mfg",
    "336411": "Aircraft Manufacturing",
    "336412": "Aircraft Engine & Parts Manufacturing",
    "336413": "Other Aircraft Parts & Accessories",
    "336414": "Guided Missile & Space Vehicle Mfg",
    "336415": "Guided Missile Propulsion Unit Mfg",
    "336419": "Other Guided Missile & Space Vehicle",
    "336510": "Railroad Rolling Stock Manufacturing",
    "336611": "Ship Building & Repairing",
    "336612": "Boat Building",
    "336991": "Motorcycle & Parts Manufacturing",
    "336992": "Military Armored Vehicle & Tank Mfg",
    "336999": "Other Transportation Equipment",
    # IT & Data
    "511210": "Software Publishers",
    "517110": "Wired Telecommunications Carriers",
    "517210": "Wireless Telecommunications Carriers",
    "517311": "Telephone Wire & Cable Contractors",
    "517312": "Wireless Telecommunications Contractors",
    "517410": "Satellite Telecommunications",
    "517910": "Other Telecommunications",
    "518210": "Data Processing & Hosting Services",
    "519130": "Internet Publishing & Broadcasting",
    "519190": "Other Information Services",
    # Professional & Technical Services
    "541110": "Offices of Lawyers",
    "541191": "Title Abstract & Settlement Offices",
    "541199": "Other Legal Services",
    "541211": "CPA Firms",
    "541213": "Tax Preparation Services",
    "541214": "Payroll Services",
    "541219": "Other Accounting Services",
    "541310": "Architectural Services",
    "541320": "Landscape Architecture Services",
    "541330": "Engineering Services",
    "541340": "Drafting Services",
    "541350": "Building Inspection Services",
    "541360": "Geophysical Surveying Services",
    "541370": "Surveying & Mapping Services",
    "541380": "Testing Laboratories",
    "541410": "Interior Design Services",
    "541420": "Industrial Design Services",
    "541430": "Graphic Design Services",
    "541490": "Other Specialized Design Services",
    "541511": "Custom Computer Programming Services",
    "541512": "Computer Systems Design Services",
    "541513": "Computer Facilities Management Services",
    "541519": "Other Computer Related Services",
    "541611": "Administrative Management Consulting",
    "541612": "Human Resources Consulting",
    "541613": "Marketing Consulting",
    "541614": "Process & Logistics Consulting",
    "541618": "Other Management Consulting",
    "541620": "Environmental Consulting",
    "541690": "Scientific & Technical Consulting",
    "541711": "Biotech Research & Development",
    "541712": "Physical & Engineering R&D",
    "541713": "Nanotechnology Research",
    "541714": "Biotechnology Research",
    "541715": "Research & Development Services",
    "541720": "Social Sciences R&D",
    "541810": "Advertising Agencies",
    "541820": "Public Relations Agencies",
    "541830": "Media Buying Agencies",
    "541840": "Media Representatives",
    "541850": "Outdoor Advertising",
    "541890": "Other Services Related to Advertising",
    "541910": "Market Research & Public Opinion Polling",
    "541921": "Photography Studios",
    "541922": "Commercial Photography",
    "541930": "Translation & Interpretation Services",
    "541940": "Veterinary Services",
    "541990": "All Other Professional & Technical Services",
    # Administrative & Support
    "561110": "Office Administrative Services",
    "561120": "Facilities Support Services",
    "561210": "Facilities Management & Support",
    "561310": "Employment Placement Agencies",
    "561320": "Temporary Staffing Agencies",
    "561330": "Professional Employer Organizations",
    "561410": "Document Preparation Services",
    "561421": "Telephone Answering Services",
    "561422": "Telemarketing Bureaus",
    "561431": "Private Mail Centers",
    "561439": "Other Business Service Centers",
    "561440": "Collection Agencies",
    "561450": "Credit Bureaus",
    "561491": "Repossession Services",
    "561499": "Other Business Support Services",
    "561510": "Travel Agencies",
    "561520": "Tour Operators",
    "561590": "Other Travel Arrangement Services",
    "561611": "Investigation Services",
    "561612": "Security Guard & Patrol Services",
    "561613": "Armored Car Services",
    "561621": "Security Systems Services",
    "561622": "Locksmiths",
    "561710": "Exterminating & Pest Control",
    "561720": "Janitorial Services",
    "561730": "Landscaping Services",
    "561740": "Carpet & Upholstery Cleaning",
    "561790": "Other Services to Buildings & Dwellings",
    "561910": "Packaging & Labeling Services",
    "561920": "Convention & Trade Show Organizers",
    "561990": "All Other Support Services",
    # Waste Management & Remediation
    "562111": "Solid Waste Collection",
    "562112": "Hazardous Waste Collection",
    "562119": "Other Waste Collection",
    "562211": "Hazardous Waste Treatment & Disposal",
    "562212": "Solid Waste Landfill",
    "562213": "Solid Waste Combustors & Incinerators",
    "562219": "Other Non-Hazardous Waste Treatment",
    "562910": "Remediation Services",
    "562920": "Materials Recovery Facilities",
    "562991": "Septic Tank & Related Services",
    "562998": "Other Miscellaneous Waste Management",
    # Education
    "611110": "Elementary & Secondary Schools",
    "611210": "Junior Colleges",
    "611310": "Colleges & Universities",
    "611410": "Business & Secretarial Schools",
    "611420": "Computer Training",
    "611430": "Professional & Management Training",
    "611511": "Cosmetology Schools",
    "611512": "Flight Training",
    "611519": "Other Technical & Trade Schools",
    "611610": "Fine Arts Schools",
    "611620": "Athletics & Recreation Instruction",
    "611630": "Language Schools",
    "611699": "All Other Miscellaneous Schools",
    "611710": "Educational Support Services",
    # Healthcare
    "621111": "Offices of Physicians",
    "621112": "Offices of Physicians, Mental Health",
    "621210": "Offices of Dentists",
    "621310": "Offices of Chiropractors",
    "621320": "Offices of Optometrists",
    "621330": "Offices of Mental Health Practitioners",
    "621340": "Offices of Physical Therapists",
    "621391": "Offices of Podiatrists",
    "621399": "Offices of Other Health Practitioners",
    "621410": "Family Planning Centers",
    "621420": "Outpatient Mental Health Centers",
    "621491": "HMO Medical Centers",
    "621492": "Kidney Dialysis Centers",
    "621493": "Freestanding Ambulatory Surgery Centers",
    "621498": "Other Outpatient Care Centers",
    "621511": "Medical Laboratories",
    "621512": "Diagnostic Imaging Centers",
    "621610": "Home Health Care Services",
    "621910": "Ambulance Services",
    "621991": "Blood & Organ Banks",
    "621999": "Other Ambulatory Health Care Services",
    "622110": "General Medical & Surgical Hospitals",
    "622210": "Psychiatric & Substance Abuse Hospitals",
    "622310": "Specialty Hospitals",
    "623110": "Nursing Care Facilities",
    "623210": "Residential Intellectual Disability",
    "623220": "Residential Mental Health Facilities",
    "623311": "Continuing Care Retirement Communities",
    "623312": "Assisted Living Facilities",
    "623990": "Other Residential Care Facilities",
    # Transportation & Logistics
    "481111": "Scheduled Passenger Air Transportation",
    "481112": "Scheduled Freight Air Transportation",
    "481211": "Nonscheduled Chartered Air Transportation",
    "481212": "Nonscheduled Air Freight Charters",
    "481219": "Other Nonscheduled Air Transportation",
    "483111": "Deep Sea Freight Transportation",
    "483112": "Deep Sea Passenger Transportation",
    "483113": "Coastal & Great Lakes Freight",
    "483114": "Coastal & Great Lakes Passenger",
    "484110": "General Freight Trucking, Local",
    "484121": "General Freight Trucking, Long-Distance",
    "484122": "General Freight Trucking, Full Truckload",
    "484210": "Used Household & Office Goods Moving",
    "484220": "Specialized Freight Trucking, Local",
    "484230": "Specialized Freight Trucking, Long-Distance",
    "485111": "Mixed Mode Transit Systems",
    "485112": "Commuter Rail Systems",
    "485113": "Bus & Motor Vehicle Transit Systems",
    "485119": "Other Urban Transit Systems",
    "485210": "Interurban & Rural Bus Transportation",
    "485310": "Taxi Service",
    "485320": "Limousine Service",
    "485410": "School & Employee Bus Transportation",
    "485510": "Charter Bus Industry",
    "485990": "Other Transit & Ground Passenger",
    "487110": "Scenic & Sightseeing Transportation, Land",
    "488111": "Air Traffic Control",
    "488119": "Other Airport Operations",
    "488190": "Other Support Activities for Air Transportation",
    "488210": "Support Activities for Rail Transportation",
    "488310": "Port & Harbor Operations",
    "488320": "Marine Cargo Handling",
    "488330": "Navigational Services to Shipping",
    "488390": "Other Support for Water Transportation",
    "488410": "Motor Vehicle Towing",
    "488490": "Other Support for Road Transportation",
    "488510": "Freight Transportation Arrangement",
    "488991": "Packing & Crating",
    "488999": "Other Support Activities for Transportation",
    "491110": "Postal Service",
    "492110": "Couriers & Express Delivery Services",
    "492210": "Local Messengers & Local Delivery",
    "493110": "General Warehousing & Storage",
    "493120": "Refrigerated Warehousing & Storage",
    "493130": "Farm Product Warehousing & Storage",
    "493190": "Other Warehousing & Storage",
    # Maintenance & Repair
    "811111": "General Automotive Repair",
    "811112": "Automotive Exhaust System Repair",
    "811113": "Automotive Transmission Repair",
    "811118": "Other Automotive Mechanical Repair",
    "811121": "Automotive Body & Paint Shops",
    "811122": "Automotive Glass Replacement Shops",
    "811191": "Automotive Oil Change & Lubrication",
    "811192": "Car Washes",
    "811198": "All Other Automotive Repair & Maintenance",
    "811210": "Electronic Equipment Repair & Maintenance",
    "811211": "Computer Hardware Repair & Maintenance",
    "811212": "Computer & Office Machine Repair",
    "811213": "Communication Equipment Repair",
    "811219": "Other Electronic Equipment Repair",
    "811310": "Commercial & Industrial Machinery Repair",
    "811411": "Home & Garden Equipment Repair",
    "811412": "Appliance Repair & Maintenance",
    "811420": "Reupholstery & Furniture Repair",
    "811430": "Footwear & Leather Goods Repair",
    "811490": "Other Personal & Household Goods Repair",
    # Public Safety
    "922110": "Courts",
    "922120": "Police Protection",
    "922130": "Legal Counsel & Prosecution",
    "922140": "Correctional Institutions",
    "922150": "Parole Offices & Probation Offices",
    "922160": "Fire Protection",
    "922190": "Other Justice & Public Order",
    "928110": "National Security",
    "928120": "International Affairs",
}

PSC_TITLES = {
    "11": "Nuclear Ordnance",
    "12": "Fire Control Equipment",
    "13": "Ammunition & Explosives",
    "14": "Guided Missiles",
    "15": "Aircraft Structures",
    "16": "Aircraft Components",
    "19": "Ships & Small Craft",
    "20": "Ship & Marine Equipment",
    "23": "Ground Effect Vehicles",
    "24": "Trucks & Tractors",
    "25": "Vehicle Components",
    "28": "Engines & Turbines",
    "29": "Engine Accessories",
    "30": "Mechanical Power Transmission",
    "31": "Bearings",
    "34": "Metalworking Machinery",
    "36": "Special Industry Machinery",
    "38": "Construction & Mining Equipment",
    "39": "Materials Handling Equipment",
    "41": "Refrigeration & AC Equipment",
    "42": "Fire Fighting & Safety Equipment",
    "43": "Pumps & Compressors",
    "44": "Furnace & Steam Plant Equipment",
    "45": "Plumbing & Heating Equipment",
    "46": "Water Purification Equipment",
    "47": "Pipe, Tubing & Fittings",
    "48": "Valves",
    "49": "Maintenance & Repair Equipment",
    "51": "Hand Tools",
    "52": "Measuring Tools",
    "53": "Hardware & Abrasives",
    "54": "Prefabricated Structures",
    "56": "Construction Materials",
    "58": "Communication & Detection Equipment",
    "59": "Electronic Components",
    "61": "Electric Wire & Power Equipment",
    "62": "Lighting Equipment",
    "63": "Alarm & Signal Systems",
    "65": "Medical & Dental Equipment",
    "66": "Instruments & Lab Equipment",
    "68": "Chemicals & Chemical Products",
    "69": "Training Aids & Devices",
    "70": "Computers & Peripherals",
    "71": "Furniture",
    "72": "Household & Commercial Furnishings",
    "74": "Office Machines",
    "75": "Office Supplies",
    "79": "Cleaning Equipment & Supplies",
    "81": "Containers & Packaging",
    "83": "Textiles & Leather",
    "84": "Clothing & Individual Equipment",
    "89": "Subsistence (Food)",
    "91": "Fuels & Lubricants",
    "95": "Metal Materials",
    "99": "Miscellaneous",
    # Letter-prefix service categories
    "A": "Research & Development",
    "B": "Special Studies & Analysis",
    "C": "Architect & Engineering Services",
    "D": "IT & Telecom Services",
    "F": "Natural Resources Management",
    "H": "Quality Control & Testing",
    "J": "Maintenance, Repair & Overhaul",
    "K": "Modification of Equipment",
    "L": "Technical Representative Services",
    "M": "Operation of Government Facilities",
    "N": "Installation of Equipment",
    "Q": "Medical Services",
    "R": "Professional & Management Support",
    "S": "Utilities & Housekeeping",
    "T": "Photography, Mapping & Printing",
    "U": "Education & Training",
    "V": "Transportation & Delivery",
    "W": "Equipment Lease & Rental",
    "Y": "Construction of Structures",
    "Z": "Maintenance of Real Property",
}


def get_sb():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def decode_jwt_payload(token: str) -> dict | None:
    """Decode Supabase JWT payload without signature verification.
    Security note: Supabase RLS + our manual company_id scoping handle
    authorization. The JWT just tells us who is calling.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.b64decode(payload_b64))
    except Exception:
        return None


def get_user_id() -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    payload = decode_jwt_payload(auth[7:])
    return payload.get("sub") if payload else None


def require_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 200
        if not get_user_id():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_opportunity(opp: dict, profile: dict) -> int:
    """
    Score an opportunity against a company profile. Returns 0–100.
    Phase 1: pure rule-based weighted scoring. No ML yet.
    """
    score = 0

    naics_codes = {n["naics_code"] for n in profile.get("naics", [])}
    keywords = [k["keyword"].lower() for k in profile.get("keywords", []) if not k.get("is_exclusion")]
    exclusion_keywords = [k["keyword"].lower() for k in profile.get("keywords", []) if k.get("is_exclusion")]
    target_agencies = {a["agency_name"].lower() for a in profile.get("agencies", []) if a.get("relationship_type") in ("past_performance", "target")}
    excluded_agencies = {a["agency_name"].lower() for a in profile.get("agencies", []) if a.get("relationship_type") == "exclude"}
    contract_min = profile.get("contract_min") or 0
    contract_max = profile.get("contract_max") or float("inf")
    set_aside_eligibility = set(profile.get("set_aside_eligibility") or [])

    # Hard exclusions — return 0 immediately
    agency_lower = (opp.get("agency") or "").lower()
    if any(excl in agency_lower for excl in excluded_agencies):
        return 0

    desc_lower = (opp.get("description") or "").lower()
    title_lower = (opp.get("title") or "").lower()
    text = f"{title_lower} {desc_lower}"
    if any(kw in text for kw in exclusion_keywords):
        return 0

    # NAICS match — worth 35 points
    opp_naics = opp.get("naics_code") or ""
    if opp_naics in naics_codes:
        score += 35
    elif any(opp_naics.startswith(n[:4]) for n in naics_codes if len(n) >= 4):
        score += 15  # Related NAICS (same 4-digit group)

    # Set-aside alignment — worth 20 points
    opp_set_aside = (opp.get("set_aside_type") or "").upper()
    set_aside_map = {
        "SBA": "small_business",
        "8AN": "8a",
        "8A": "8a",
        "SDVOSBC": "sdvosb",
        "SDVOSBR": "sdvosb",
        "WOSB": "wosb",
        "EDWOSB": "wosb",
        "HZC": "hubzone",
        "HZS": "hubzone",
        "": "none",
        "NONE": "none",
    }
    normalized_set_aside = set_aside_map.get(opp_set_aside, "")
    if not opp_set_aside or normalized_set_aside == "none":
        score += 10  # Unrestricted — anyone can bid
    elif normalized_set_aside in set_aside_eligibility:
        score += 20  # Matches their eligibility

    # Contract value in range — worth 15 points
    opp_value = opp.get("value_max") or opp.get("value_min")
    if opp_value:
        if contract_min <= float(opp_value) <= contract_max:
            score += 15
        elif float(opp_value) < contract_min * 0.5 or float(opp_value) > contract_max * 2:
            score -= 10  # Way outside range

    # Agency affinity — worth 15 points
    if any(ta in agency_lower for ta in target_agencies):
        score += 15

    # Keyword overlap — worth up to 15 points
    if keywords:
        matches = sum(1 for kw in keywords if kw in text)
        keyword_score = min(15, int((matches / max(len(keywords), 1)) * 15 * 3))
        score += keyword_score

    # Deadline urgency adjustment
    deadline_str = opp.get("response_deadline")
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_left = (deadline - now).days
            if days_left < 0:
                return 0  # Expired
            elif days_left <= 7:
                score += 5   # Closing soon — boost visibility
            elif days_left <= 21:
                score += 2
        except ValueError:
            pass

    return max(0, min(100, score))


def build_company_profile(sb, company_id: str) -> dict:
    """Fetch company + related tables and return a unified profile dict."""
    company = sb.table("companies").select("*").eq("id", company_id).single().execute()
    naics = sb.table("company_naics").select("*").eq("company_id", company_id).execute()
    keywords = sb.table("company_keywords").select("*").eq("company_id", company_id).execute()
    agencies = sb.table("company_agencies").select("*").eq("company_id", company_id).execute()

    profile = company.data or {}
    profile["naics"] = naics.data or []
    profile["keywords"] = keywords.data or []
    profile["agencies"] = agencies.data or []
    return profile


# ---------------------------------------------------------------------------
# Feed endpoint
# ---------------------------------------------------------------------------

@app.route("/api/v2/feed", methods=["GET"])
@require_auth
def get_feed():
    """
    Returns a scored, ranked list of opportunity cards for the user's company.
    Excludes opportunities the user has already swiped.

    Query params:
      limit  — number of cards to return (default 20)
      offset — for pagination (default 0)
      mode   — 'algorithm' (default) or 'recent' (bypass scoring, show newest)
    """
    user_id = get_user_id()
    limit = min(int(request.args.get("limit", 20)), 50)
    mode = request.args.get("mode", "algorithm")

    sb = get_sb()

    # Get user's company
    user_row = sb.table("users").select("company_id").eq("id", user_id).single().execute()
    if not user_row.data:
        return jsonify({"error": "User not found. Complete onboarding first."}), 404
    company_id = user_row.data["company_id"]

    # Get already-swiped opportunity IDs for this user
    swiped = sb.table("swipes").select("opportunity_id").eq("user_id", user_id).execute()
    swiped_ids = [s["opportunity_id"] for s in (swiped.data or [])]

    # Fetch candidate opportunities from Supabase
    # Pre-filter: active status, not already swiped
    # Note: don't filter by deadline here — many valid records (awards, pre-sols,
    # sources sought) have null deadlines. Scoring handles expired ones (returns 0).
    now_iso = datetime.now(timezone.utc).isoformat()
    query = (
        sb.table("opportunities")
        .select("id,notice_id,title,agency,sub_agency,naics_code,psc_code,set_aside_type,notice_type,value_min,value_max,pop_city,pop_state,response_deadline,posted_date,ai_summary,description,status,source,attachments")
        .eq("status", "active")
        .in_("notice_type", ACTIONABLE_NOTICE_TYPES)
        .order("posted_date", desc=True)
        .limit(500)  # Candidate pool for scoring
    )

    # Exclude already-swiped opportunities
    if swiped_ids:
        query = query.not_.in_("id", swiped_ids)

    result = query.execute()
    candidates = result.data or []

    if not candidates:
        return jsonify({"cards": [], "total": 0, "exhausted": True})

    if mode == "recent":
        # Just return newest, no scoring
        cards = [format_card(o) for o in candidates[:limit]]
        return jsonify({"cards": cards, "total": len(candidates)})

    # Score all candidates against company profile
    profile = build_company_profile(sb, company_id)
    scored = [(score_opportunity(o, profile), o) for o in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Mix: 70% top scorers, 20% exploration, 10% urgency
    top_n = int(limit * 0.7)
    explore_n = int(limit * 0.2)
    urgent_n = limit - top_n - explore_n

    top_cards = [o for _, o in scored[:top_n]]

    # Exploration: take from mid-range scorers
    mid = scored[top_n: top_n + 50]
    random.shuffle(mid)
    explore_cards = [o for _, o in mid[:explore_n]]

    # Urgency: closing within 14 days, pick from remaining
    remaining = [o for _, o in scored[top_n:] if o not in explore_cards]
    urgent_cards = _pick_urgent(remaining, urgent_n)

    final = top_cards + explore_cards + urgent_cards
    random.shuffle(final[top_n:])  # Shuffle explore/urgent so they don't cluster at the end

    # Build score lookup for final set
    score_map = {id(o): s for s, o in scored}

    # Resolve URL descriptions synchronously before building cards.
    # All SAM.gov records store a noticedesc API URL in the description field.
    # We fetch the real text in parallel (up to 6 concurrent, 12s timeout) so the
    # detail view has content on this response. Fetched text is written back to the
    # DB in a background thread so subsequent loads are instant.
    url_desc_opps = [o for o in final if (o.get("description") or "").strip().startswith("http")]
    if url_desc_opps:
        fetched_descs = _fetch_descriptions_parallel(url_desc_opps)
        if fetched_descs:
            opp_by_id = {o["id"]: o for o in final}
            for opp_id, text in fetched_descs.items():
                if opp_id in opp_by_id:
                    opp_by_id[opp_id]["description"] = text
            # Persist to DB in background — next load skips the fetch entirely
            def _persist_descriptions(desc_map):
                sb2 = get_sb()
                for oid, txt in desc_map.items():
                    try:
                        sb2.table("opportunities").update({"description": txt}).eq("id", oid).execute()
                    except Exception as e:
                        logger.warning(f"Description persist failed for {oid}: {e}")
            threading.Thread(
                target=_persist_descriptions,
                args=(dict(fetched_descs),),
                daemon=True,
            ).start()

    # Kick off summary generation in a background thread — don't block the response.
    # Cards that already have ai_summary cached in the DB come back populated.
    # New ones will be ready on the next feed load or on-demand fetch.
    if ANTHROPIC_API_KEY:
        needs_summary = [o for o in final[:12] if not o.get("ai_summary")]
        if needs_summary:
            _start_background_summaries(needs_summary)

    cards = [format_card(o, score=score_map.get(id(o))) for o in final]

    return jsonify({"cards": cards, "total": len(candidates)})


def _start_background_summaries(opps: list) -> None:
    """Fire-and-forget: generate summaries and write to DB without blocking the feed response."""
    def _worker():
        sb = get_sb()
        generated = _bulk_generate_summaries(opps)
        for opp_id, summary_text in generated.items():
            try:
                sb.table("opportunities").update({"ai_summary": summary_text}).eq("id", opp_id).execute()
            except Exception as e:
                logger.warning(f"Background summary cache failed for {opp_id}: {e}")
    threading.Thread(target=_worker, daemon=True).start()


def _clean_description_text(text: str) -> str:
    """Normalize plain-text description: reflow paragraphs, strip noise.
    - Converts single newlines within a paragraph to spaces (reflowing text)
    - Preserves paragraph breaks (blank lines)
    - Strips leading/trailing whitespace from each line
    - Collapses excessive blank lines
    """
    if not text:
        return ""
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Split into blocks on blank lines
    blocks = re.split(r'\n{2,}', text)
    cleaned_blocks = []
    for block in blocks:
        # Within each block, collapse newlines and extra spaces to a single space
        lines = [line.strip() for line in block.split('\n')]
        joined = ' '.join(l for l in lines if l)
        if joined:
            cleaned_blocks.append(joined)
    return '\n\n'.join(cleaned_blocks).strip()


def _fetch_description_text(notice_id: str, max_chars: int = 1500) -> str:
    """Fetch real description HTML from SAM.gov and convert to clean plain text.
    Preserves paragraph structure. Returns empty string on any failure."""
    if not SAM_API_KEY or not notice_id:
        return ""
    try:
        url = (
            f"https://api.sam.gov/prod/opportunities/v1/noticedesc"
            f"?noticeid={notice_id}&api_key={SAM_API_KEY}"
        )
        resp = http_requests.get(url, timeout=6)
        if resp.status_code != 200:
            logger.warning(f"SAM noticedesc returned {resp.status_code} for notice_id={notice_id}")
            return ""
        html = resp.text
        # Convert block-level elements to newlines before stripping tags
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</(p|div|li|tr|h[1-6])>', '\n', html, flags=re.IGNORECASE)
        # Strip remaining tags
        text = re.sub(r'<[^>]+>', '', html)
        # Decode common HTML entities
        text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
                .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'"))
        return _clean_description_text(text)[:max_chars]
    except Exception as e:
        logger.warning(f"Description fetch failed for {notice_id}: {e}")
        return ""


def _fetch_descriptions_parallel(opps: list) -> dict:
    """Fetch real description text from SAM.gov for all opps whose description field is a URL.
    Returns {opp_id: text}. Never raises. Uses up to 6 parallel workers with 12s timeout."""
    url_opps = [o for o in opps if (o.get("description") or "").strip().startswith("http")]
    if not url_opps:
        return {}

    results = {}

    def _fetch_one(opp):
        text = _fetch_description_text(opp.get("notice_id", ""), max_chars=8000)
        return opp["id"], text

    with ThreadPoolExecutor(max_workers=min(len(url_opps), 6)) as ex:
        futures = {ex.submit(_fetch_one, o): o["id"] for o in url_opps}
        try:
            for future in as_completed(futures, timeout=12):
                try:
                    opp_id, text = future.result()
                    if text:
                        results[opp_id] = text
                except Exception as e:
                    logger.warning(f"Desc fetch future error: {e}")
        except Exception:
            logger.warning("Description parallel fetch timed out — returning partial results")
    return results


def _generate_one_summary(opp: dict) -> tuple[str, str | None]:
    """Call Claude Haiku to generate a plain-English title for one opportunity.
    Returns (opp_id, plain_title|None). Short prompt — max 30 tokens out."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        raw_desc = opp.get("description") or ""
        desc_snippet = "None" if raw_desc.strip().startswith("http") else (raw_desc[:120] or "None")

        title = _clean_title(opp.get("title", ""))
        notice_type = opp.get("notice_type", "")
        psc = opp.get("psc_code", "") or ""
        naics = opp.get("naics_code", "")

        prompt = f"""Write a plain-English one-line description (10–15 words) explaining what this federal contract is for.

Input:
Title: {title}
Notice type: {notice_type}
PSC: {psc} — {_get_psc_title(psc) or ''}
NAICS: {naics} — {_get_naics_title(naics) or ''}
Description snippet: {desc_snippet}

Instructions:
1. Identify type: SUPPLY / SERVICES / R&D / CONSTRUCTION
2. Describe what is being bought and who the buyer is
3. Expand abbreviations: ASSEMB→Assembly, ELEC→Electric, ATCT→Air Traffic Control Tower, SVC→Services
4. Do NOT repeat jargon like solicitation, procurement, RFQ
5. If unclear, stick to a literal interpretation — do NOT invent details

Rules:
- 10–15 words max
- Output only the final description line"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        return opp.get("id"), response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Summary generation failed for {opp.get('id')}: {e}")
        return opp.get("id"), None


def _bulk_generate_summaries(opps: list) -> dict:
    """Generate summaries for multiple opportunities in parallel. Returns {opp_id: summary}.
    Never raises — feed endpoint must not crash due to AI errors."""
    results = {}
    executor = ThreadPoolExecutor(max_workers=min(len(opps), 4))
    try:
        futures = {executor.submit(_generate_one_summary, o): o["id"] for o in opps}
        try:
            for future in as_completed(futures, timeout=8):
                try:
                    opp_id, summary = future.result()
                    if summary:
                        results[opp_id] = summary
                except Exception as e:
                    logger.warning(f"Summary future failed: {e}")
        except Exception:
            # TimeoutError or other — return what we have so far
            logger.warning("Summary pre-generation timed out, returning partial results")
    except Exception as e:
        logger.warning(f"Bulk summary failed to start: {e}")
    finally:
        executor.shutdown(wait=False)
    return results


def _pick_urgent(opps: list, n: int) -> list:
    """Return up to n opportunities with deadlines within 14 days."""
    now = datetime.now(timezone.utc)
    urgent = []
    for o in opps:
        dl = o.get("response_deadline")
        if not dl:
            continue
        try:
            deadline = datetime.fromisoformat(dl.replace("Z", "+00:00"))
            if 0 < (deadline - now).days <= 14:
                urgent.append(o)
        except ValueError:
            continue
    return urgent[:n]


def _clean_title(title: str) -> str:
    """Clean SAM.gov titles for human readability."""
    text = (title or '').strip()
    if not text:
        return text
    # Strip PSC/FSC prefix patterns: "47--", "J--", "R699--", "17--GUIDE,"
    text = re.sub(r'^[A-Z0-9]{1,6}--\s*', '', text)
    # Add space after commas if missing
    text = re.sub(r',(?!\s)', ', ', text)
    # Title-case if mostly uppercase (>60% uppercase alpha chars)
    alpha = [c for c in text if c.isalpha()]
    if alpha and sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.6:
        # Custom title case that handles acronyms better
        words = text.split()
        stop = {'and', 'or', 'of', 'the', 'for', 'in', 'at', 'to', 'a', 'an',
                'with', 'on', 'by', 'from', 'its', 'as'}
        # Known 4-5 char acronyms common in federal contracting
        known_acronyms = {
            'HVAC', 'USAF', 'USMC', 'USMC', 'NASA', 'DISA', 'DCSA', 'ITAR',
            'DTRA', 'AUSA', 'SOCOM', 'NAICS', 'DARPA', 'CONUS', 'OCONUS',
        }
        result = []
        for i, w in enumerate(words):
            wl = w.lower()
            # Treat ≤3-char all-caps or known acronyms as acronyms to preserve
            is_acronym = (
                w.isupper() and w.isalpha() and wl not in stop and
                (len(w) <= 3 or w in known_acronyms)
            )
            if is_acronym:
                result.append(w)
            elif i == 0 or wl not in stop:
                result.append(w.capitalize())
            else:
                result.append(wl)
        text = ' '.join(result)
    return text.strip() or (title or '').strip()


def _get_naics_title(code: str) -> str:
    return NAICS_TITLES.get(str(code).strip(), "") if code else ""


def _get_psc_title(code: str) -> str:
    if not code:
        return ""
    code = str(code).strip().upper()
    return (PSC_TITLES.get(code) or
            PSC_TITLES.get(code[:2]) or
            PSC_TITLES.get(code[:1]) or "")


def _parse_scope(description: str) -> dict:
    """Parse DLA-style description text for structured scope data without AI.
    Handles format: 'NSN XXXX Line 0001 Qty N UI EA Deliver To: X By: N DAYS ADO'
    Also handles quantity-only patterns for non-DLA supply contracts.
    """
    if not description or description.strip().startswith("http"):
        return {}
    text = description.upper()
    original = description  # preserve case for item name extraction
    result = {}

    # NSN
    nsn = re.search(r'NSN\s+(\d{4}-\d{2}-\d{3}-\d{4}|\d{10,13})', text)
    if nsn:
        result["nsn"] = nsn.group(1)

    # Line items: qty + unit
    line_items = re.findall(r'LINE\s+\d+\s+QTY\s+([\d.]+)\s+UI\s+(\w+)', text)
    if line_items:
        total_qty = sum(float(q) for q, _ in line_items)
        unit = line_items[0][1]
        result["qty_display"] = f"{int(total_qty) if total_qty == int(total_qty) else total_qty} {unit.lower()}"

    # Item name: look for ITEM NAME or NOMENCLATURE or the text after NSN line
    item_match = re.search(
        r'(?:ITEM\s+NAME|NOMENCLATURE|ITEM\s+DESC(?:RIPTION)?)[:\s]+([^\n\r.]{3,60})',
        text
    )
    if item_match:
        result["item_name"] = item_match.group(1).strip().title()
    elif nsn:
        # Try to grab the descriptive text that follows the NSN on the same line
        nsn_line = re.search(
            r'NSN\s+[\d\-]+[,\s]+([A-Z][A-Z\s,/\-]{3,50}?)(?:\s+LINE|\s+QTY|\s+DELIVER|$)',
            text
        )
        if nsn_line:
            result["item_name"] = nsn_line.group(1).strip().title()

    # Delivery days (pick min/max for ranges across multiple line items)
    deliveries = re.findall(r'BY:\s+(\d+)\s+DAYS?\s+ADO', text)
    if deliveries:
        days = sorted(set(int(d) for d in deliveries))
        result["delivery_display"] = f"{days[0]}–{days[-1]} days ADO" if len(days) > 1 else f"{days[0]} days ADO"

    # Approved sources
    source = re.search(r'APPROVED\s+SOURCES?\s+(?:ARE|IS)\s+([^.]+)\.', text)
    if source:
        result["approved_source"] = source.group(1).strip().title()

    return result


def _safe_desc(text: str, max_len: int = 200) -> str:
    """Return text truncated to max_len, or '' if it's just a URL."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("http"):
        return ""
    return text[:max_len]


def _extract_deadline_from_description(description: str) -> int | None:
    """
    Try to extract a response deadline from free-text description.
    Returns days remaining from today (int), or None if not found.
    Handles patterns like:
      "proposals due May 8, 2026"
      "extended to May 8, 2026, at 2:00 pm"
      "offers due by April 30, 2026"
      "closing date: March 15, 2026"
      "responses due NLT 15 Apr 2026"
    """
    if not description or description.strip().startswith("http"):
        return None

    text = description

    # Month name patterns (written dates)
    months = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )

    # Trigger keywords that precede a date
    triggers = (
        r"(?:proposals?\s+due|offers?\s+due|responses?\s+due|"
        r"extended\s+to|closing\s+date[:\s]|due\s+(?:by|date|NLT)|"
        r"deadline[:\s]|submit(?:ted)?\s+(?:by|no\s+later\s+than)|"
        r"no\s+later\s+than|NLT)"
    )

    # Pattern A: "Month DD, YYYY" or "Month DD YYYY"
    pattern_a = (
        rf"{triggers}\s+(?:\w+\s+)?({months}\s+\d{{1,2}}[,\s]+\d{{4}})"
    )
    # Pattern B: "DD Month YYYY" (military style)
    pattern_b = (
        rf"{triggers}\s+(?:\w+\s+)?(\d{{1,2}}\s+{months}\s+\d{{4}})"
    )
    # Pattern C: loose — any "Month DD, YYYY" within 30 chars of trigger keyword
    pattern_c = rf"({months}\s+\d{{1,2}},\s+\d{{4}})"

    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def parse_written_date(s: str) -> datetime | None:
        s = s.strip().rstrip(",").strip()
        # Try "Month DD, YYYY" or "Month DD YYYY"
        m = re.match(
            rf"({months})\s+(\d{{1,2}})[,\s]+(\d{{4}})", s, re.IGNORECASE
        )
        if m:
            mon = month_map.get(m.group(1).lower())
            if mon:
                try:
                    return datetime(int(m.group(3)), mon, int(m.group(2)),
                                    tzinfo=timezone.utc)
                except ValueError:
                    pass
        # Try "DD Month YYYY"
        m = re.match(
            rf"(\d{{1,2}})\s+({months})\s+(\d{{4}})", s, re.IGNORECASE
        )
        if m:
            mon = month_map.get(m.group(2).lower())
            if mon:
                try:
                    return datetime(int(m.group(3)), mon, int(m.group(1)),
                                    tzinfo=timezone.utc)
                except ValueError:
                    pass
        return None

    now = datetime.now(timezone.utc)

    for pattern in [pattern_a, pattern_b]:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            dt = parse_written_date(m.group(1))
            if dt and dt > now:
                return (dt - now).days

    # Fallback: any "Month DD, YYYY" in the text that is in the future
    for m in re.finditer(pattern_c, text, re.IGNORECASE):
        dt = parse_written_date(m.group(1))
        if dt and dt > now:
            return (dt - now).days

    return None


def _estimate_complexity(naics_code: str) -> str:
    """Estimate bid complexity from NAICS code prefix. Returns Low / Medium / High."""
    if not naics_code:
        return "Medium"
    code = str(naics_code).strip()
    prefix4 = code[:4]
    prefix3 = code[:3]
    prefix2 = code[:2]

    high = {
        "5417",  # R&D
        "5416",  # Management/scientific consulting
        "5415",  # IT design & dev
        "3364",  # Aircraft & missile manufacturing
        "3363",  # Motor vehicle parts — complex
        "3344",  # Semiconductor
        "3345",  # Navigational instruments
        "9281",  # National security
    }
    low = {
        "3325",  # Hardware
        "3327",  # Machine shops / precision
        "3329",  # Small arms / ammunition
        "4841",  # Trucking
        "4931",  # Warehousing
        "5617",  # Janitorial
        "5611",  # Office admin
        "5619",  # Packaging/labeling
        "8112",  # Computer hardware repair
        "8113",  # Industrial machinery repair
        "3119",  # Food manufacturing
        "3121",  # Beverages
    }

    if prefix4 in high or prefix3 in {"541", "928"}:
        return "High"
    if prefix4 in low or prefix2 in {"49", "56", "81"}:
        return "Low"

    # Construction is Medium
    if prefix2 in {"23"}:
        return "Medium"
    # Services generally Medium
    if prefix2 in {"54", "61", "62", "72"}:
        return "Medium"

    return "Medium"


def _extract_flags(description: str, set_aside: str) -> list:
    """Extract disqualifier/qualifier flags from description text.
    Returns list of {type, label} dicts for rendering as pills on the card."""
    flags = []
    if not description or description.strip().startswith("http"):
        return flags
    text = description.upper()

    # Security clearance
    if re.search(r'\bTS[/ ]?SCI\b|TOP SECRET[/ ]SCI', text):
        flags.append({"type": "clearance", "label": "TS/SCI"})
    elif re.search(r'\bTOP SECRET\b|\bTS\b CLEARANCE', text):
        flags.append({"type": "clearance", "label": "Top Secret"})
    elif re.search(r'\bSECRET\b CLEARANCE|\bCLEARANCE REQUIRED\b|\bSECURITY CLEARANCE\b', text):
        flags.append({"type": "clearance", "label": "Secret Clearance"})

    # CMMC
    cmmc = re.search(r'CMMC\s*(?:LEVEL\s*)?([123])', text)
    if cmmc:
        flags.append({"type": "cert", "label": f"CMMC L{cmmc.group(1)}"})
    elif re.search(r'\bCMMC\b', text):
        flags.append({"type": "cert", "label": "CMMC"})

    # Quality certifications
    if re.search(r'\bAS9100\b|\bAS9102\b|\bNADCAP\b', text):
        flags.append({"type": "cert", "label": "AS9100/NADCAP"})
    elif re.search(r'\bISO\s*9001\b', text):
        flags.append({"type": "cert", "label": "ISO 9001"})

    # ITAR / export control
    if re.search(r'\bITAR\b|\bEAR\s*CONTROLLED\b|\bEXPORT\s*CONTROLLED\b', text):
        flags.append({"type": "cert", "label": "ITAR/EAR"})

    # Contract vehicles
    if re.search(r'\bDIBBS\b|DLA\s*INTERNET\s*BID', text):
        flags.append({"type": "vehicle", "label": "DIBBS"})
    elif re.search(r'\bGSA\s*SCHEDULE\b|FEDERAL\s*SUPPLY\s*SCHEDULE\b|\bFSS\b', text):
        flags.append({"type": "vehicle", "label": "GSA Schedule"})
    elif re.search(r'\bSEWAAS\b|\bSEATEC\b|\bOASIS\b|\bALLIANT\b|\bSTARSS\b', text):
        flags.append({"type": "vehicle", "label": "GWAC Required"})

    # Sole source signal
    if re.search(r'\bSOLE\s*SOURCE\b|\bSINGLE\s*SOURCE\b|\bAPPROVED\s*SOURCE\b', text):
        flags.append({"type": "sole", "label": "Sole Source"})

    return flags[:4]  # Cap at 4 to prevent pill overflow


def format_card(opp: dict, score: int = None) -> dict:
    """Shape an opportunity into the minimal card payload the frontend needs."""
    # Deadline display
    deadline_str = opp.get("response_deadline")
    days_left = None
    urgency = "normal"
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            days_left = (deadline - datetime.now(timezone.utc)).days
            if days_left <= 7:
                urgency = "red"
            elif days_left <= 21:
                urgency = "yellow"
            else:
                urgency = "green"
        except ValueError:
            pass

    # Value display
    value_display = None
    if opp.get("value_max"):
        v = float(opp["value_max"])
        if v >= 1_000_000_000:
            value_display = f"${v/1_000_000_000:.1f}B"
        elif v >= 1_000_000:
            value_display = f"${v/1_000_000:.1f}M"
        elif v >= 1_000:
            value_display = f"${v/1_000:.0f}K"
        else:
            value_display = f"${v:.0f}"

    naics_code = opp.get("naics_code", "") or ""
    psc_code = opp.get("psc_code", "") or ""
    naics_title = _get_naics_title(naics_code)
    psc_title = _get_psc_title(psc_code)
    # Industry label: prefer NAICS name, fall back to PSC category
    industry_label = naics_title or psc_title or ""
    # Location display
    pop_city = opp.get("pop_city", "") or ""
    pop_state = opp.get("pop_state", "") or ""
    location = ", ".join(filter(None, [pop_city, pop_state]))
    # Description-derived fields
    raw_desc = opp.get("description", "") or ""
    # Some records store description as a JSON object {"description": "..."}
    if raw_desc.strip().startswith("{"):
        try:
            parsed_json = json.loads(raw_desc)
            if isinstance(parsed_json, dict):
                raw_desc = parsed_json.get("description") or parsed_json.get("body") or raw_desc
        except Exception:
            pass
    set_aside = opp.get("set_aside_type", "") or ""
    flags = _extract_flags(raw_desc, set_aside)
    parsed_scope = _parse_scope(raw_desc)
    complexity = _estimate_complexity(naics_code)

    # Derived deadline: fall back to parsing description text when DB field is null
    derived_days = None
    if days_left is None:
        derived_days = _extract_deadline_from_description(raw_desc)
    effective_days = days_left if days_left is not None else derived_days
    if effective_days is not None and days_left is None and derived_days is not None:
        # Recalculate urgency for derived deadline
        if derived_days <= 7:
            urgency = "red"
        elif derived_days <= 21:
            urgency = "yellow"
        else:
            urgency = "green"

    return {
        "id": opp["id"],
        "notice_id": opp.get("notice_id"),
        "title": _clean_title(opp.get("title", "")),
        "agency": opp.get("agency", ""),
        "sub_agency": opp.get("sub_agency", ""),
        "naics_code": naics_code,
        "naics_title": naics_title,
        "psc_code": psc_code,
        "psc_title": psc_title,
        "industry_label": industry_label,
        "location": location,
        "flags": flags,
        "complexity": complexity,
        "set_aside_type": set_aside,
        "notice_type": opp.get("notice_type", ""),
        "value_display": value_display,
        "pop_city": pop_city,
        "pop_state": pop_state,
        "days_left": effective_days,
        "days_left_derived": derived_days is not None and days_left is None,
        "urgency": urgency,
        "response_deadline": deadline_str,
        "posted_date": opp.get("posted_date"),
        "ai_summary": opp.get("ai_summary"),
        "parsed_scope": parsed_scope,
        # Raw description text when it's actual text (not a SAM.gov URL).
        # URLs are resolved to real text in get_feed() before format_card() is called.
        # Apply _clean_description_text() to normalize paragraph structure.
        "description_text": _clean_description_text(raw_desc)[:8000] if raw_desc and not raw_desc.strip().startswith("http") else None,
        "attachments": opp.get("attachments") or "[]",
        "has_attachments": bool(opp.get("attachments") and opp["attachments"] != "[]"),
        "score": score,
        "sam_url": f"https://sam.gov/opp/{opp.get('notice_id')}/view",
    }


# ---------------------------------------------------------------------------
# AI summary endpoint (on-demand, cached in DB)
# ---------------------------------------------------------------------------

@app.route("/api/v2/opportunities/<opp_id>/summary", methods=["POST"])
@require_auth
def generate_summary(opp_id: str):
    """
    Generate and cache an AI one-line summary for an opportunity card.
    Called when a card is rendered and ai_summary is null.
    """
    sb = get_sb()

    # Check if already generated (race condition safety)
    existing = sb.table("opportunities").select("ai_summary").eq("id", opp_id).single().execute()
    if existing.data and existing.data.get("ai_summary"):
        return jsonify({"summary": existing.data["ai_summary"]})

    opp = sb.table("opportunities").select("id,notice_id,title,agency,sub_agency,description,naics_code,psc_code,set_aside_type,notice_type,value_max,pop_city,pop_state").eq("id", opp_id).single().execute()
    if not opp.data:
        return jsonify({"error": "Not found"}), 404

    _, summary_text = _generate_one_summary(opp.data)
    if not summary_text:
        return jsonify({"error": "Summary generation failed"}), 500

    # Cache in database
    sb.table("opportunities").update({"ai_summary": summary_text}).eq("id", opp_id).execute()
    return jsonify({"summary": summary_text})


# ---------------------------------------------------------------------------
# Opportunity detail
# ---------------------------------------------------------------------------

@app.route("/api/v2/opportunities/<opp_id>/analysis", methods=["POST"])
@require_auth
def get_analysis(opp_id: str):
    """
    Generate a structured 4-section analysis for the detail view.
    Checks DB cache (ai_analysis column) first — returns instantly if cached.
    Returns: { analysis: str, confidence: 'high'|'low' }
    """
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "AI not configured"}), 503

    sb = get_sb()
    opp = sb.table("opportunities").select(
        "id,notice_id,title,agency,sub_agency,naics_code,psc_code,set_aside_type,"
        "notice_type,value_max,pop_city,pop_state,response_deadline,description,ai_summary,ai_analysis,attachments"
    ).eq("id", opp_id).single().execute()

    if not opp.data:
        return jsonify({"error": "Not found"}), 404

    o = opp.data

    # Return cached analysis immediately if available
    if o.get("ai_analysis"):
        return jsonify({"analysis": o["ai_analysis"], "confidence": "high", "cached": True})

    raw_desc = o.get("description") or ""

    # Fetch full description — this is the expensive step (SAM.gov HTTP call)
    if raw_desc.strip().startswith("http"):
        desc_text = _fetch_description_text(o.get("notice_id", ""))
    else:
        desc_text = raw_desc[:1500]

    confidence = "high" if len(desc_text) > 200 else "low"

    # Parse structured scope from description
    parse_source = raw_desc if not raw_desc.strip().startswith("http") else desc_text
    scope = _parse_scope(parse_source)
    scope_lines = []
    if scope.get("qty_display"):
        scope_lines.append(f"Qty: {scope['qty_display']}")
    if scope.get("delivery_display"):
        scope_lines.append(f"Delivery: {scope['delivery_display']}")
    if scope.get("approved_source"):
        scope_lines.append(f"Approved source: {scope['approved_source']}")

    # Format supporting fields
    value = o.get("value_max")
    value_str = ""
    if value:
        v = float(value)
        value_str = f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"

    days_left_str = ""
    deadline = o.get("response_deadline")
    if deadline:
        try:
            dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            days = (dl - datetime.now(timezone.utc)).days
            days_left_str = f"{days} days remaining"
        except Exception:
            pass

    pop = ", ".join(filter(None, [o.get("pop_city"), o.get("pop_state")]))
    naics_code = o.get("naics_code", "") or ""
    psc_code = o.get("psc_code", "") or ""
    plain_title = o.get("ai_summary") or _clean_title(o.get("title", ""))

    prompt = f"""You are helping a contractor decide whether to bid on a federal contract.

IMPORTANT:
- Prioritize structured fields (quantities, delivery, etc.) over description text
- If description is missing or weak, rely on available data and explicitly say what is unknown
- Do NOT hallucinate

Opportunity:
Title: {plain_title}
Agency: {o.get('agency', '')} / {o.get('sub_agency', '')}
Type: {o.get('notice_type', '')} | Set-aside: {o.get('set_aside_type', '') or 'None'}
NAICS: {naics_code} — {_get_naics_title(naics_code) or 'N/A'}
PSC: {psc_code} — {_get_psc_title(psc_code) or 'N/A'}
{f"Estimated value: {value_str}" if value_str else ""}
{f"Deadline: {days_left_str}" if days_left_str else ""}
{f"Place of performance: {pop}" if pop else ""}
{f"Structured data: {'; '.join(scope_lines)}" if scope_lines else ""}

Description:
{desc_text if desc_text else "Not available"}

---

Step 1 — Identify contract type:
SUPPLY / SERVICES / R&D / CONSTRUCTION

---

Then write:

**Overview**
2–3 sentences:
- What is being procured
- Who the buyer is
- Type of procurement
- If description is weak, say so clearly

---

**Key Details**
Bullet points:
- ALWAYS include structured data if available
- Fill gaps with description if present
- If missing, write "Not stated"

---

**Requirements**
Bullet points:
- Extract only explicit requirements
- If description is weak:
  → "Requirements not available in synopsis — review solicitation documents"

Then:
Technical Complexity: Low / Medium / High
(1-line justification based on contract type and clarity)

---

**Risk & Effort**
Bullet points. Be analytical, not generic:
- Is this commodity vs specialized?
- Is scope clearly defined?
- Any risk signals:
  - short deadline
  - missing specs
  - sole source hints
  - restricted set-aside
  - external RFQ required (e.g., DIBBS)

---

Rules:
- Be concise but specific
- Use actual numbers and facts
- Do NOT repeat the title
- Do NOT invent details"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis_text = response.content[0].text.strip()
        # Cache in DB so future opens are instant
        try:
            sb.table("opportunities").update({"ai_analysis": analysis_text}).eq("id", opp_id).execute()
        except Exception as cache_err:
            logger.warning(f"Failed to cache analysis for {opp_id}: {cache_err}")
        return jsonify({"analysis": analysis_text, "confidence": confidence})
    except Exception as e:
        logger.error(f"Analysis generation failed for {opp_id}: {e}")
        # Return a structured fallback so the frontend can still show metadata
        fallback = (
            f"**Overview**\n"
            f"Analysis could not be generated for this opportunity. "
            f"Review the full listing on SAM.gov for details.\n\n"
            f"**Key Details**\n"
            f"- Agency: {o.get('agency', 'N/A')}\n"
            f"- Notice type: {o.get('notice_type', 'N/A')}\n"
            f"- NAICS: {naics_code} — {_get_naics_title(naics_code) or 'See lookup'}\n"
            f"- PSC: {psc_code} — {_get_psc_title(psc_code) or 'See listing'}\n"
            + (f"- Est. value: {value_str}\n" if value_str else "")
            + (f"- Deadline: {days_left_str}\n" if days_left_str else "")
            + "\n**Requirements**\n- See solicitation documents on SAM.gov\n\n"
            f"**Risk & Effort**\n- Full analysis unavailable — visit SAM.gov for complete details"
        )
        return jsonify({"analysis": fallback, "confidence": "low"})


@app.route("/api/v2/opportunities/<opp_id>", methods=["GET"])
@require_auth
def get_opportunity(opp_id: str):
    """Full opportunity detail for the expanded card view."""
    sb = get_sb()
    result = sb.table("opportunities").select("*").eq("id", opp_id).single().execute()
    if not result.data:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result.data)


# ---------------------------------------------------------------------------
# Company profile (read — writes go direct to Supabase from frontend)
# ---------------------------------------------------------------------------

@app.route("/api/v2/company/profile", methods=["GET"])
@require_auth
def get_company_profile():
    user_id = get_user_id()
    sb = get_sb()
    user_row = sb.table("users").select("company_id").eq("id", user_id).single().execute()
    if not user_row.data:
        return jsonify({"error": "User not found"}), 404
    profile = build_company_profile(sb, user_row.data["company_id"])
    return jsonify(profile)


# ---------------------------------------------------------------------------
# Registration — create company + user records using service key (bypasses RLS)
# Called from the frontend after supabase.auth.signUp() succeeds
# ---------------------------------------------------------------------------

@app.route("/api/v2/auth/register", methods=["POST"])
def register():
    """
    Creates company and user records after Supabase Auth signup.
    Uses the service key so RLS doesn't block the inserts.
    Expects: { user_id, email, company_name }
    """
    data = request.get_json()
    user_id = data.get("user_id")
    email = data.get("email")
    company_name = data.get("company_name")

    if not all([user_id, email, company_name]):
        return jsonify({"error": "user_id, email, and company_name are required"}), 400

    sb = get_sb()

    # Check if user row already exists (idempotent)
    existing = sb.table("users").select("id,company_id").eq("id", user_id).execute()
    if existing.data:
        company = sb.table("companies").select("*").eq("id", existing.data[0]["company_id"]).single().execute()
        return jsonify({"company": company.data})

    try:
        # Create company
        company_result = sb.table("companies").insert({
            "name": company_name,
            "onboarding_complete": False,
            "onboarding_step": 1,
        }).execute()
        company_data = company_result.data[0]

        # Create user linked to company
        sb.table("users").insert({
            "id": user_id,
            "company_id": company_data["id"],
            "email": email,
            "role": "admin",
        }).execute()

        return jsonify({"company": company_data})
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/v2/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.0"})


@app.errorhandler(Exception)
def handle_exception(e):
    """Global catch-all so unhandled exceptions return JSON + CORS instead of dropping the connection."""
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    response = jsonify({"error": "Internal server error", "detail": str(e)})
    response.status_code = 500
    return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    logger.info(f"Starting Platform API v2 on port {port}")
    # debug=False prevents the Werkzeug reloader from spawning a child process,
    # which conflicts with ThreadPoolExecutor and causes connection drops on Windows.
    app.run(host="127.0.0.1", port=port, debug=False)
