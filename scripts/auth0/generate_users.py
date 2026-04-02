#!/usr/bin/env python3
"""
Generate 100 mock users for the NovaTech Solutions Auth0 sandbox.

Outputs: novatech_users.json — the user dataset used by provisioning scripts and the /bulk-provision skill.

Department distribution mirrors a realistic 100-person SaaS startup:
  Engineering: 30, Data: 10, Product: 8, Design: 5,
  IT-Ops: 5, Finance: 5, HR: 5, Sales: 15, Marketing: 10, Executive: 7
"""

import json
import random
import string
from datetime import datetime, timedelta

# Department configuration
DEPARTMENTS = {
    "Engineering": {
        "count": 30,
        "auth0_role": "engineer",
        "aws_permission_set": "PowerUser",
        "cost_center": "ENG-100",
        "github_team": "engineering",
        "jira_role": "developer",
        "titles": [
            "Software Engineer", "Senior Software Engineer", "Staff Engineer",
            "Frontend Engineer", "Backend Engineer", "DevOps Engineer",
            "Site Reliability Engineer", "Platform Engineer",
            "Engineering Manager", "Principal Engineer"
        ],
    },
    "Data": {
        "count": 10,
        "auth0_role": "data-engineer",
        "aws_permission_set": "PowerUser",
        "cost_center": "DATA-500",
        "github_team": "data-engineering",
        "jira_role": "developer",
        "titles": [
            "Data Engineer", "Senior Data Engineer", "ML Engineer",
            "Data Scientist", "Analytics Engineer", "Data Platform Engineer",
            "ML Operations Engineer"
        ],
    },
    "Product": {
        "count": 8,
        "auth0_role": "product",
        "aws_permission_set": "ReadOnly",
        "cost_center": "PROD-600",
        "github_team": "product",
        "jira_role": "product-manager",
        "titles": [
            "Product Manager", "Senior Product Manager", "Product Analyst",
            "Technical Product Manager", "VP Product"
        ],
    },
    "Design": {
        "count": 5,
        "auth0_role": "designer",
        "aws_permission_set": "ReadOnly",
        "cost_center": "DES-700",
        "github_team": "design",
        "jira_role": "designer",
        "titles": [
            "Product Designer", "Senior Product Designer", "UX Researcher",
            "Design Lead", "Visual Designer"
        ],
    },
    "IT-Ops": {
        "count": 5,
        "auth0_role": "it-admin",
        "aws_permission_set": "Admin",
        "cost_center": "IT-200",
        "github_team": "it-operations",
        "jira_role": "it-admin",
        "titles": [
            "IT Systems Engineer", "Senior IT Engineer", "IT Operations Manager",
            "Help Desk Technician", "IT Security Analyst"
        ],
    },
    "Finance": {
        "count": 5,
        "auth0_role": "finance",
        "aws_permission_set": "ReadOnly",
        "cost_center": "FIN-300",
        "github_team": "finance",
        "jira_role": "viewer",
        "titles": [
            "Controller", "Senior Accountant", "Financial Analyst",
            "Accounts Payable Specialist", "FP&A Manager"
        ],
    },
    "HR": {
        "count": 5,
        "auth0_role": "hr",
        "aws_permission_set": "ReadOnly",
        "cost_center": "HR-800",
        "github_team": "people-ops",
        "jira_role": "viewer",
        "titles": [
            "HR Manager", "People Operations Specialist", "Recruiter",
            "HR Business Partner", "Benefits Administrator"
        ],
    },
    "Sales": {
        "count": 15,
        "auth0_role": "sales",
        "aws_permission_set": "ReadOnly",
        "cost_center": "SALES-900",
        "github_team": "sales",
        "jira_role": "viewer",
        "titles": [
            "Account Executive", "Senior Account Executive",
            "Sales Development Representative", "Sales Manager",
            "VP Sales", "Solutions Engineer", "Sales Operations Analyst"
        ],
    },
    "Marketing": {
        "count": 10,
        "auth0_role": "marketing",
        "aws_permission_set": "ReadOnly",
        "cost_center": "MKT-1000",
        "github_team": "marketing",
        "jira_role": "viewer",
        "titles": [
            "Marketing Manager", "Content Marketing Specialist",
            "Growth Marketing Manager", "Demand Gen Manager",
            "Marketing Operations Analyst", "Brand Designer",
            "Product Marketing Manager"
        ],
    },
    "Executive": {
        "count": 7,
        "auth0_role": "executive",
        "aws_permission_set": "ReadOnly",
        "cost_center": "EXEC-400",
        "github_team": "leadership",
        "jira_role": "admin",
        "titles": [
            "CEO", "CTO", "CFO", "VP Engineering",
            "VP Sales", "VP Marketing", "COO"
        ],
    },
}

# Realistic first/last name pools
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Christopher", "Karen", "Charles", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Ruth",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward",
    "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel",
    "Myers", "Long", "Ross", "Foster", "Jimenez", "Powell",
]


def generate_password(length=20):
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choices(chars, k=length))


def generate_start_date():
    """Generate a realistic start date (within last 3 years)."""
    days_ago = random.randint(1, 1095)  # Up to 3 years
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def generate_users():
    """Generate the full 100-user dataset."""
    users = []
    used_emails = set()

    random.seed(42)  # Reproducible generation

    for dept_name, dept_config in DEPARTMENTS.items():
        for i in range(dept_config["count"]):
            # Pick unique name combo
            while True:
                first = random.choice(FIRST_NAMES)
                last = random.choice(LAST_NAMES)
                email = f"{first.lower()}.{last.lower()}@novatech.io"
                if email not in used_emails:
                    used_emails.add(email)
                    break

            title = dept_config["titles"][i % len(dept_config["titles"])]

            # Pick a manager (first person in department, or CEO for dept heads)
            manager_email = "james.smith@novatech.io"  # CEO default
            if i > 0 and len(users) > 0:
                # Manager is the first person in this department
                dept_users = [u for u in users if u["user_metadata"]["department"] == dept_name]
                if dept_users:
                    manager_email = dept_users[0]["email"]

            user = {
                "email": email,
                "name": f"{first} {last}",
                "given_name": first,
                "family_name": last,
                "password": generate_password(),
                "connection": "Username-Password-Authentication",
                "email_verified": True,
                "user_metadata": {
                    "department": dept_name,
                    "role_title": title,
                    "cost_center": dept_config["cost_center"],
                    "manager_email": manager_email,
                    "start_date": generate_start_date(),
                },
                "app_metadata": {
                    "aws_permission_set": dept_config["aws_permission_set"],
                    "github_team": dept_config["github_team"],
                    "jira_role": dept_config["jira_role"],
                    "provisioned_by": "novatech-sandbox-generator",
                    "provisioned_date": datetime.now().strftime("%Y-%m-%d"),
                },
                "auth0_role": dept_config["auth0_role"],
            }
            users.append(user)

    return users


def main():
    users = generate_users()

    # Write full dataset
    output_path = "scripts/auth0/novatech_users.json"
    with open(output_path, "w") as f:
        json.dump(users, f, indent=2)
    print(f"Generated {len(users)} users → {output_path}")

    # Print summary
    dept_counts = {}
    for u in users:
        dept = u["user_metadata"]["department"]
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    print("\nDepartment breakdown:")
    for dept, count in sorted(dept_counts.items()):
        print(f"  {dept}: {count}")

    # Write a summary CSV for quick reference
    csv_path = "scripts/auth0/novatech_users_summary.csv"
    with open(csv_path, "w") as f:
        f.write("email,name,department,role_title,auth0_role,aws_permission_set\n")
        for u in users:
            f.write(
                f"{u['email']},"
                f"{u['name']},"
                f"{u['user_metadata']['department']},"
                f"{u['user_metadata']['role_title']},"
                f"{u['auth0_role']},"
                f"{u['app_metadata']['aws_permission_set']}\n"
            )
    print(f"Summary CSV → {csv_path}")


if __name__ == "__main__":
    main()
