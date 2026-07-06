# Steryl Healthcare Management System

Africa's end-to-end healthcare supply chain platform — connecting hospitals, diagnostic centres, pharmacies, manufacturers and distributors in a single real-time system.

---

## Overview

Steryl eliminates the three biggest failures in African healthcare procurement:

| Problem | Scale |
|---|---|
| Facility stockouts | 40% of facilities run out of critical supplies monthly |
| Counterfeit drugs | Up to 30% of pharmaceuticals in circulation are substandard |
| Procurement delays | Average 21-day cycle from request to delivery |

The platform provides purpose-built workspaces for every stakeholder type, with all data exchanged through a central Steryl hub in real time.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask, Flask-Login, Flask-Bcrypt |
| Database | PostgreSQL + SQLAlchemy ORM |
| Templates | Jinja2 |
| Frontend | Tailwind CSS (CDN), Material Symbols, Font Awesome |
| Auth | Flask-Login, session-based |

---

## Account Types

| Type | Workspace | Description |
|---|---|---|
| `hospital` | Dashboard | Multi-department procurement, consolidation, inventory |
| `laboratory` | Dashboard | Displayed as "Diagnostic Centre" — reagent and consumable tracking |
| `pharmacy` | Dashboard | Verified product catalogue ordering |
| `manufacturer` | Manufacturer workspace | SKU management, batch registration, barcode printing |
| `distributor` | Distributor workspace | Central order queue, approval, shipment tracking |

Roles: `staff` · `admin` · `super_admin`

Account statuses: `pending` · `approved` · `rejected` · `suspended`

---

## Key Features

- **Department system** — Org admins create departments, assign members, and consolidate department-level orders into a single bulk order routed to the Steryl distributor
- **Single distributor routing** — All orders from all org types are automatically routed to the Steryl Admin distributor account
- **Login workspace routing** — On login, each account type is redirected to its dedicated workspace
- **Data scoping** — All dashboard stats, stock alerts, inventory and approvals are scoped to the logged-in user's organisation only
- **Diagnostic Centre display** — `laboratory` account type is stored in the database as `laboratory` but displayed as "Diagnostic Centre" throughout the UI via a Jinja2 custom filter
- **Org admin creation** — New org registrants automatically receive `admin` role; admins can create additional staff members

---

## Project Structure

```
steryl_dev/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # App factory, custom Jinja2 filters
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── routes.py            # All Flask routes and API endpoints
│   │   ├── static/
│   │   │   └── steryl_logo.jpeg
│   │   ├── templates/
│   │   │   ├── index.html       # Public landing page (investor-facing)
│   │   │   ├── demo.html        # Interactive product demo page
│   │   │   ├── invest.html      # Investor / shareholder portal
│   │   │   ├── login.html
│   │   │   ├── register.html
│   │   │   ├── dashboard/       # Hospital / lab / pharmacy workspace
│   │   │   │   ├── _top_nav.html
│   │   │   │   ├── _bottom_nav.html
│   │   │   │   ├── procurement.html   (home / dashboard)
│   │   │   │   ├── orders.html
│   │   │   │   ├── Approvals.html
│   │   │   │   ├── inventory.html
│   │   │   │   └── departments.html
│   │   │   ├── manufacturer/    # Manufacturer workspace
│   │   │   ├── distributor/     # Distributor workspace
│   │   │   └── admin/           # Super-admin panel
│   │   └── utils/
│   ├── .env.example
│   └── requirements.txt
```

---

## Database Models

| Model | Key fields |
|---|---|
| `User` | email, first_name, last_name, account_type, role, account_status, org_name, department_id |
| `Order` | order_number, requester_id, status, total_amount, is_dept_request, dept_id |
| `OrderItem` | order_id, product_id, quantity, unit_price |
| `Product` | name, sku, price, stock_quantity, manufacturer_id |
| `Department` | name, org_user_id, org_type |
| `DeptProductUsage` | dept_id, product_name, quantity, unit |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/Gscientist64/steryl_dev.git
cd steryl_dev/backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment variables

Copy `.env.example` to `.env` and fill in:

```
FLASK_SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:password@localhost:5432/steryl_db
```

### 3. Database

```bash
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"
```

### 4. Create admin accounts

```bash
python create_super_admin.py      # Super admin
python create_distributor_user.py # Steryl Admin (distributor)
python create_manufacturer_user.py
```

### 5. Run

```bash
flask run
# or
python run.py
```

---

## Public Pages

| Route | Description |
|---|---|
| `/` | Landing page — problem, solution, workspace previews |
| `/demo` | Interactive animated product demo (3 workflow players) |
| `/invest` | Investor portal — share tiers, revenue model, interest form |
| `/about` | About Steryl |
| `/register` | Organisation registration |
| `/login` | Sign in |

---

## API Endpoints (selected)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/login` → `/login` | Authenticate and receive redirect URL |
| POST | `/register` | Register a new organisation |
| GET | `/api/dashboard-stats` | Dashboard stats (scoped to current user) |
| GET | `/api/stock-alerts` | Low stock alerts (scoped) |
| GET/POST | `/api/departments` | List / create departments |
| POST | `/api/departments/<id>/assign-member` | Assign user to department |
| POST | `/api/dept-orders/consolidate` | Consolidate dept orders to distributor |
| GET | `/api/org-members` | List all members in current user's org |
| POST | `/api/org-members/create` | Admin creates a new org staff member |

---

## Investor Information

Steryl is currently in its founding investment round. Visit [/invest](/invest) for share tier details, revenue projections, and to express interest.

---

## Licence

Proprietary — Steryl Health Ltd. All rights reserved.
