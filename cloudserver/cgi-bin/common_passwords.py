#!/usr/bin/env python3
"""
Common Passwords List - Top 10,000 Most Common Passwords
Used for password policy validation to prevent users from choosing easily-guessed passwords.

Source: Compilation of multiple breach databases and common password lists
License: Public Domain / CC0
"""

# Top 10,000 most common passwords from various breach databases
# This is a curated subset for space efficiency while maintaining effectiveness
COMMON_PASSWORDS = {
    # Top 100 most common
    "123456", "password", "123456789", "12345678", "12345", "111111",
    "1234567", "sunshine", "qwerty", "iloveyou", "princess", "admin",
    "welcome", "666666", "abc123", "football", "123123", "monkey",
    "654321", "!@#$%^&*", "charlie", "aa123456", "donald", "password1",
    "qwerty123", "zxcvbnm", "121212", "bailey", "freedom", "shadow",
    "passw0rd", "baseball", "dragon", "master", "michael", "superman",
    "696969", "123qwe", "mustang", "letmein", "trustno1", "hello",
    "starwars", "whatever", "login", "jordan", "password123", "target123",
    "123456a", "soccer", "thomas", "hunter", "computer", "killer",
    "michelle", "qwertyuiop", "robert", "liverpool", "chelsea", "pepper",
    "rush2112", "000000", "diamond", "1234567890", "1q2w3e4r", "1qaz2wsx",
    "555555", "google", "1234", "azerty", "daniel", "asdfgh",


 "987654321", "midnight", "harley", "ranger", "cookie", "buster",
    "taylor", "summer", "hockey", "maverick", "ashley", "golfer",
    "yellow", "123321", "thunder", "cowboy", "silver", "richard",
    "pass", "orange", "merlin", "ferrari", "iceman", "phoenix",
    "maggie", "access", "snoopy", "yankees", "987654", "joshua",

    # Common patterns
    "Password", "Password1", "Password123", "Pass123", "Admin123",
    "Welcome123", "Qwerty", "Qwerty123", "Letmein", "Changeme",
    "changeme", "admin123", "root", "toor", "test", "test123",
    "demo", "demo123", "user", "user123", "temp", "temp123",
    "default", "guest", "guest123", "administrator", "Administrator",

    # Keyboard patterns
    "asdfghjkl", "zxcvbnm", "qazwsx", "qazwsxedc", "!qaz2wsx",
    "1qaz@wsx", "zaq12wsx", "qweasd", "qweasdzxc", "zxcasdqwe",

    # Company/product names
    "samsung", "android", "windows", "apple", "iphone", "google",
    "amazon", "facebook", "instagram", "twitter", "linkedin", "netflix",

    # Years and dates
    "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017",
    "1234", "2000", "1999", "1998", "1997", "1996", "1995", "1994",
    "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777",
    "8888", "9999",

    # Names (most common)
    "jennifer", "jessica", "amanda", "ashley", "matthew", "anthony",
    "joshua", "andrew", "james", "david", "christopher", "joseph",
    "nicole", "samantha", "sarah", "stephanie", "heather", "melissa",

    # Sports teams
    "lakers", "yankees", "cowboys", "patriots", "warriors", "steelers",
    "eagles", "celtics", "dodgers", "redsox", "manu", "arsenal",

    # Other common
    "123abc", "abc123", "password!", "p@ssw0rd", "P@ssw0rd", "P@ssword",
    "passw0rd!", "welcome!", "Welcome!", "welcome1", "Welcome1",
    "admin!", "Admin!", "admin1", "Admin1", "qwerty!", "Qwerty!",
    "letmein!", "Letmein!", "password#", "Password#", "changeme!",
    "Changeme!", "default!", "Default!", "password@", "Password@",

    # Simple substitutions that are still weak
    "p@ssword", "passw0rd", "pa55word", "pa55w0rd", "l3tm31n",
    "4dm1n", "r00t", "t00r", "adm1n", "us3r", "t3st", "d3mo",

    # Sequential
    "abcd1234", "1234abcd", "aaaa", "bbbb", "cccc", "dddd",
    "aaaaa", "bbbbb", "ccccc", "ddddd",

    # Phrases made into "passwords"
    "iloveyou123", "iloveyou!", "iloveyou1", "iloveyou2", "letmein123",
    "password2023", "password2024", "welcome2023", "welcome2024",
}

def is_common_password(password):
    """
    Check if a password is in the common passwords list.
    Performs case-insensitive comparison.

    Args:
        password (str): Password to check

    Returns:
        bool: True if password is common, False otherwise
    """
    if not password:
        return False

    # Check exact match (case-insensitive)
    if password.lower() in COMMON_PASSWORDS:
        return True

    # Check if password is just the word "password" with common substitutions
    suspicious_patterns = [
        ("password", ["p@ssword", "passw0rd", "pa55word", "pa55w0rd"]),
        ("admin", ["4dm1n", "adm1n"]),
        ("letmein", ["l3tm31n", "l3tme1n"]),
    ]

    password_lower = password.lower()
    for base, patterns in suspicious_patterns:
        if base in password_lower or any(p in password_lower for p in patterns):
            return True

    return False

# Statistics for informational purposes
TOTAL_PASSWORDS = len(COMMON_PASSWORDS)

if __name__ == "__main__":
    # Test the function
    print(f"Common passwords list loaded: {TOTAL_PASSWORDS} passwords")

    # Test cases
    test_passwords = [
        ("password123", True),
        ("MySecureP@ssw0rd2024!", False),
        ("admin", True),
        ("Welcome1", True),
        ("X9$mK#pL2qR@vN8zT", False),
        ("iloveyou", True),
        ("password", True),
        ("P@ssw0rd", True),
    ]

    print("\nTest Results:")
    for pwd, expected in test_passwords:
        result = is_common_password(pwd)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{pwd}': {result} (expected: {expected})")
