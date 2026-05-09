#!/usr/bin/env python3
"""Synthetic borrower data generator for credit underwriting engine.
Generates 10,000 loan applications with realistic correlations."""

import csv
import random
import math
import os

random.seed(42)

# Output paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRAIN_PATH = os.path.join(BASE_DIR, 'train.csv')
VAL_PATH = os.path.join(BASE_DIR, 'val.csv')
TEST_PATH = os.path.join(BASE_DIR, 'test.csv')
FEATURES_PATH = os.path.join(BASE_DIR, 'feature_importance_ref.csv')

FEATURES = [
    'age', 'annual_income', 'employment_length', 'credit_score',
    'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
    'home_ownership_rent', 'home_ownership_mortgage', 'home_ownership_own',
    'loan_amount', 'loan_purpose_encoded', 'loan_to_income',
    'debt_payment_ratio', 'credit_utilization_score', 'account_diversity',
    'risk_flags'
]

TARGET = 'default_flag'

LOAN_PURPOSES = ['debt_consolidation', 'home_improvement', 'medical', 'education', 'business', 'personal']

# Ground truth feature weights for generating default probability
# These simulate the "true" underlying risk model
TRUE_WEIGHTS = {
    'credit_score': -0.85,
    'dti_ratio': 0.60,
    'utilization': 0.50,
    'num_derogatory': 0.55,
    'home_ownership_rent': 0.30,
    'home_ownership_own': -0.15,
    'home_ownership_mortgage': -0.10,
    'employment_length': -0.15,
    'annual_income': -0.20,
    'loan_to_income': 0.35,
    'num_credit_lines': 0.10,
    'age': -0.10,
    'loan_purpose_business': 0.15,
    'loan_purpose_debt_consolidation': 0.20,
    'loan_purpose_medical': 0.25,
    'loan_purpose_education': 0.05,
    'loan_purpose_home_improvement': -0.05,
    'loan_purpose_personal': 0.10,
    'intercept': -2.5,
}


def generate_borrower():
    """Generate a single synthetic borrower with realistic feature correlations."""
    age = random.randint(22, 70)

    # Income correlates with age (peaks around 50-55)
    age_factor = 1.0 - 0.5 * ((age - 50) / 25) ** 2
    base_income = 40000 + random.gauss(0, 15000)
    annual_income = max(20000, min(250000, int(base_income * (0.8 + 0.4 * age_factor))))

    # Employment length capped by age
    max_emp = max(0, age - 22)
    employment_length = min(max_emp, max(0, int(random.expovariate(1 / 8))))

    # Credit score influenced by age, income, employment
    cs_mean = 650 + (age - 22) * 1.5 + (annual_income - 40000) * 0.0003 + employment_length * 2
    credit_score = max(300, min(850, int(random.gauss(cs_mean, 60))))

    # dti ratio — higher with lower income, more debt
    dti_mean = 0.20 + max(0, 0.15 - annual_income * 0.0000005) + random.uniform(-0.05, 0.05)
    dti_ratio = max(0.0, min(0.5, round(random.gauss(dti_mean, 0.08), 4)))

    # Utilization — higher with lower credit score
    util_mean = 0.3 + (650 - credit_score) * 0.001 + random.uniform(-0.05, 0.05)
    utilization = max(0.0, min(1.0, round(random.gauss(util_mean, 0.12), 4)))

    # Derogatory marks — more with lower credit score
    derog_rate = max(0.01, 0.05 + (700 - credit_score) * 0.001)
    num_derogatory = min(8, int(random.expovariate(1 / max(0.1, derog_rate))))

    # Credit lines — more with age and income
    num_credit_lines = max(1, min(30, int(random.gauss(8 + age * 0.1, 5))))

    # Home ownership correlates with age, income, credit score
    home_ownership = 'rent'
    r = random.random()
    if age > 30 and annual_income > 50000 and credit_score > 620:
        if r < 0.4:
            home_ownership = 'mortgage'
        elif r < 0.65:
            home_ownership = 'own'
        else:
            home_ownership = 'rent'
    elif age > 25 and annual_income > 35000:
        if r < 0.3:
            home_ownership = 'mortgage'
        elif r < 0.45:
            home_ownership = 'own'
        else:
            home_ownership = 'rent'
    else:
        if r < 0.15:
            home_ownership = 'mortgage'
        elif r < 0.22:
            home_ownership = 'own'
        else:
            home_ownership = 'rent'

    # Loan amount (500-50000), influenced by income and credit
    max_loan = min(50000, int(annual_income * 0.4))
    min_loan = 500
    loan_amount = random.randint(min_loan, max_loan)
    # Round to nearest 100
    loan_amount = round(loan_amount / 100) * 100

    # Loan purpose
    loan_purpose = random.choice(LOAN_PURPOSES)

    return {
        'age': age,
        'annual_income': annual_income,
        'employment_length': employment_length,
        'credit_score': credit_score,
        'dti_ratio': dti_ratio,
        'utilization': utilization,
        'num_derogatory': num_derogatory,
        'num_credit_lines': num_credit_lines,
        'home_ownership': home_ownership,
        'loan_amount': loan_amount,
        'loan_purpose': loan_purpose,
    }


def compute_default_probability(borrower):
    """Compute default probability using the true weight model.
    Using stronger weights to create meaningful signal."""
    # Derived features
    loan_to_income = borrower['loan_amount'] / max(1, borrower['annual_income'])

    home_rent = 1.0 if borrower['home_ownership'] == 'rent' else 0.0
    home_own = 1.0 if borrower['home_ownership'] == 'own' else 0.0
    home_mortgage = 1.0 if borrower['home_ownership'] == 'mortgage' else 0.0

    purpose_business = 1.0 if borrower['loan_purpose'] == 'business' else 0.0
    purpose_debt = 1.0 if borrower['loan_purpose'] == 'debt_consolidation' else 0.0
    purpose_medical = 1.0 if borrower['loan_purpose'] == 'medical' else 0.0
    purpose_education = 1.0 if borrower['loan_purpose'] == 'education' else 0.0
    purpose_home = 1.0 if borrower['loan_purpose'] == 'home_improvement' else 0.0
    purpose_personal = 1.0 if borrower['loan_purpose'] == 'personal' else 0.0

    # Normalized features for consistent scaling
    norm_credit = (borrower['credit_score'] - 300) / 550  # 0 to 1
    norm_income = (borrower['annual_income'] - 20000) / 230000  # 0 to 1 roughly
    norm_age = (borrower['age'] - 22) / 48  # 0 to 1
    norm_emp = min(1.0, borrower['employment_length'] / 20)
    norm_derog = min(1.0, borrower['num_derogatory'] / 5)

    log_odds = (
        -3.5 +  # intercept — lower base default rate (~10-15% default rate)
        -2.0 * norm_credit +  # STRONG: high credit score → much lower default
        3.0 * borrower['dti_ratio'] +  # STRONG: high DTI → higher default
        2.0 * borrower['utilization'] +  # STRONG: high utilization → higher default
        1.5 * norm_derog +  # STRONG: derogatory marks → higher default
        1.0 * home_rent +  # Renters higher risk
        3.0 * loan_to_income * 2 +  # STRONG: high loan-to-income → higher default
        0.5 * purpose_medical +
        0.4 * purpose_debt +
        -0.3 * purpose_home +
        -0.5 * norm_income +  # Higher income → lower default
        -0.3 * norm_emp  # Longer employment → lower default
    )

    prob = 1.0 / (1.0 + math.exp(-max(-500, min(500, log_odds))))
    # Clip and add slight noise for realism
    prob = max(0.01, min(0.95, prob))
    return prob


def generate_dataset(n=10000):
    """Generate n synthetic borrowers with default flags."""
    data = []
    for _ in range(n):
        borrower = generate_borrower()
        prob = compute_default_probability(borrower)
        # Add noise for realism
        noisy_prob = max(0.0, min(1.0, prob + random.gauss(0, 0.02)))
        default = 1 if random.random() < noisy_prob else 0
        borrower['default_flag'] = default
        data.append(borrower)

    return data


def write_csv(data, filepath):
    """Write dataset to CSV."""
    fieldnames = [
        'age', 'annual_income', 'employment_length', 'credit_score',
        'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
        'home_ownership', 'loan_amount', 'loan_purpose', 'default_flag'
    ]
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    actual_defaults = sum(1 for d in data if d['default_flag'] == 1)
    print(f"  Written {len(data)} records to {filepath}")
    print(f"  Default rate: {actual_defaults}/{len(data)} = {100*actual_defaults/len(data):.1f}%")


def write_feature_importance_ref(filepath):
    """Write reference feature importance for validation."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['feature', 'true_weight', 'importance_magnitude'])
        rows = [(k, v, abs(v)) for k, v in sorted(TRUE_WEIGHTS.items(), key=lambda x: -abs(x[1]))]
        writer.writerows(rows)
    print(f"  Written feature importance reference to {filepath}")


def main():
    print("Generating synthetic borrower data...")
    all_data = generate_dataset(10000)

    # Shuffle
    random.shuffle(all_data)

    # Split 70/15/15
    n = len(all_data)
    train = all_data[:int(n * 0.70)]
    val = all_data[int(n * 0.70):int(n * 0.85)]
    test = all_data[int(n * 0.85):]

    print(f"\nTotal: {n} borrowers")
    print(f"Train: {len(train)}, Val: {len(val)}, Test: {len(test)}")

    write_csv(train, TRAIN_PATH)
    write_csv(val, VAL_PATH)
    write_csv(test, TEST_PATH)

    write_feature_importance_ref(FEATURES_PATH)

    print("\nDone! Generated all datasets.")


if __name__ == '__main__':
    main()
