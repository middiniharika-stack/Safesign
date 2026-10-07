import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from web3 import Web3


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/*": {
            "origins": "*"
        }
    }
)

RPC_URL = os.getenv(
    "SEPOLIA_RPC_URL",
    "https://ethereum-sepolia-rpc.publicnode.com"
)

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").strip()

CONTRACT_ADDRESS = os.getenv(
    "CONTRACT_ADDRESS",
    ""
).strip()

EXPLORER_BASE = "https://sepolia.etherscan.io"

FRONTEND_ORIGIN = os.getenv(
    "FRONTEND_ORIGIN",
    "http://localhost:5500"
)

DATABASE_URL = os.getenv("DATABASE_URL", "")

AI_API_KEY = os.getenv("AI_API_KEY", "").strip()

AI_MODEL = os.getenv(
    "AI_MODEL",
    "gpt-4o-mini"
).strip()

AI_BASE_URL = os.getenv(
    "AI_BASE_URL",
    "https://api.openai.com/v1"
).rstrip("/")


# ============================================================
# WEB3
# ============================================================

w3 = Web3(Web3.HTTPProvider(RPC_URL))

account = None

if PRIVATE_KEY:
    try:
        account = w3.eth.account.from_key(PRIVATE_KEY)
    except Exception:
        account = None


# ============================================================
# DATABASE
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(
    BASE_DIR,
    "safesign.db"
)


def db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """
    IMPORTANT:
    This schema matches the existing safesign.db database.

    We intentionally do NOT recreate or delete the database.
    """

    conn = db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT,
            chain_id INTEGER,
            contract_address TEXT,
            function_name TEXT,
            token_address TEXT,
            amount TEXT,
            risk_score INTEGER,
            risk_level TEXT,
            flags TEXT,
            explanation TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


init_database()


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_address(value):
    try:
        return bool(value and Web3.is_address(value))
    except Exception:
        return False


def checksum_address(value):
    if not is_address(value):
        return None

    try:
        return Web3.to_checksum_address(value)
    except Exception:
        return None


def get_code(address):
    """
    Returns contract bytecode at an address.
    Empty bytes means there is no deployed contract code.
    """

    if not is_address(address):
        return None

    try:
        address = checksum_address(address)
        return w3.eth.get_code(address)
    except Exception:
        return None


def has_contract_code(address):
    code = get_code(address)

    if code is None:
        return False

    return len(code) > 0


def short_address(address):
    if not address:
        return "Unknown"

    if len(address) < 12:
        return address

    return (
        address[:6]
        + "..."
        + address[-4:]
    )


def tx_url(tx_hash):
    if not tx_hash:
        return None

    return (
        f"{EXPLORER_BASE}/tx/{tx_hash}"
    )


def safe_json_loads(value, default):
    try:
        if value is None or value == "":
            return default

        return json.loads(value)

    except Exception:
        return default


def parse_numeric_value(value):
    """
    Converts decimal or hex transaction values into integers.
    """

    if value is None:
        return 0

    try:
        if isinstance(value, int):
            return value

        value = str(value).strip()

        if value.lower().startswith("0x"):
            return int(value, 16)

        return int(value)

    except Exception:
        return 0


def wei_to_eth(value):
    try:
        return float(
            w3.from_wei(
                parse_numeric_value(value),
                "ether"
            )
        )
    except Exception:
        return 0.0


# ============================================================
# ERC-20 FUNCTION DECODING
# ============================================================

ERC20_SELECTORS = {
    "095ea7b3": "approve",
    "23b872dd": "transferFrom",
    "a9059cbb": "transfer",
    "39509351": "increaseAllowance",
    "dd62ed3e": "allowance",
    "70a08231": "balanceOf",
    "18160ddd": "totalSupply",
}


def decode_erc20_transaction(data):
    """
    Decodes common ERC-20 transaction selectors.

    Returns:
        {
            function,
            selector,
            tokenAddress,
            spender,
            recipient,
            amount,
            rawData
        }
    """

    result = {
        "function": "Unknown",
        "selector": None,
        "tokenAddress": None,
        "spender": None,
        "recipient": None,
        "amount": None,
        "rawData": data,
    }

    if not data:
        return result

    data = str(data)

    if data.startswith("0x"):
        clean_data = data[2:]
    else:
        clean_data = data

    if len(clean_data) < 8:
        return result

    selector = clean_data[:8].lower()

    result["selector"] = "0x" + selector

    result["function"] = ERC20_SELECTORS.get(
        selector,
        "Unknown"
    )

    try:

        # ----------------------------------------------------
        # approve(address,uint256)
        # ----------------------------------------------------

        if selector == "095ea7b3":

            if len(clean_data) >= 136:

                spender_hex = clean_data[8:72]
                amount_hex = clean_data[72:136]

                spender = Web3.to_checksum_address(
                    "0x" + spender_hex[-40:]
                )

                amount = int(
                    amount_hex,
                    16
                )

                result["spender"] = spender
                result["amount"] = amount

        # ----------------------------------------------------
        # transfer(address,uint256)
        # ----------------------------------------------------

        elif selector == "a9059cbb":

            if len(clean_data) >= 136:

                recipient_hex = clean_data[8:72]
                amount_hex = clean_data[72:136]

                recipient = Web3.to_checksum_address(
                    "0x" + recipient_hex[-40:]
                )

                amount = int(
                    amount_hex,
                    16
                )

                result["recipient"] = recipient
                result["amount"] = amount

        # ----------------------------------------------------
        # transferFrom(address,address,uint256)
        # ----------------------------------------------------

        elif selector == "23b872dd":

            if len(clean_data) >= 200:

                from_hex = clean_data[8:72]
                to_hex = clean_data[72:136]
                amount_hex = clean_data[136:200]

                sender = Web3.to_checksum_address(
                    "0x" + from_hex[-40:]
                )

                recipient = Web3.to_checksum_address(
                    "0x" + to_hex[-40:]
                )

                amount = int(
                    amount_hex,
                    16
                )

                result["spender"] = sender
                result["recipient"] = recipient
                result["amount"] = amount

        # ----------------------------------------------------
        # increaseAllowance(address,uint256)
        # ----------------------------------------------------

        elif selector == "39509351":

            if len(clean_data) >= 136:

                spender_hex = clean_data[8:72]
                amount_hex = clean_data[72:136]

                spender = Web3.to_checksum_address(
                    "0x" + spender_hex[-40:]
                )

                amount = int(
                    amount_hex,
                    16
                )

                result["spender"] = spender
                result["amount"] = amount

    except Exception:
        pass

    return result


# ============================================================
# RISK ENGINE
# ============================================================

def calculate_risk(
    to_address,
    data,
    value,
    decoded=None
):

    if decoded is None:
        decoded = decode_erc20_transaction(data)

    score = 0
    flags = []

    to_has_code = has_contract_code(
        to_address
    )

    # --------------------------------------------------------
    # Destination analysis
    # --------------------------------------------------------

    if to_address and not to_has_code:

        score += 15

        flags.append(
            "Destination address has no deployed contract code"
        )

    # --------------------------------------------------------
    # Function analysis
    # --------------------------------------------------------

    function_name = decoded.get(
        "function",
        "Unknown"
    )

    if function_name == "Unknown":

        score += 20

        flags.append(
            "Transaction function could not be identified"
        )

    # --------------------------------------------------------
    # Unlimited approval detection
    # --------------------------------------------------------

    amount = decoded.get("amount")

    if (
        function_name in [
            "approve",
            "increaseAllowance"
        ]
        and amount is not None
    ):

        # uint256 maximum
        MAX_UINT256 = (2 ** 256) - 1

        if amount >= MAX_UINT256:

            score += 40

            flags.append(
                "Unlimited token approval detected"
            )

    # --------------------------------------------------------
    # Spender analysis
    # --------------------------------------------------------

    spender = decoded.get(
        "spender"
    )

    if spender:

        spender_has_code = has_contract_code(
            spender
        )

        if not spender_has_code:

            score += 25

            flags.append(
                "Approval spender has no deployed contract code"
            )

    # --------------------------------------------------------
    # Native ETH transfer analysis
    # --------------------------------------------------------

    eth_value = wei_to_eth(
        value
    )

    if eth_value >= 0.1:

        score += 15

        flags.append(
            f"Large native ETH transfer: {eth_value:.4f} ETH"
        )

    # --------------------------------------------------------
    # Calldata + EOA analysis
    # --------------------------------------------------------

    if data and data != "0x":

        if not to_has_code:

            score += 10

            flags.append(
                "Calldata is being sent to an address without contract code"
            )

    # --------------------------------------------------------
    # Clamp score
    # --------------------------------------------------------

    score = max(
        0,
        min(
            score,
            100
        )
    )

    # --------------------------------------------------------
    # Risk level
    # --------------------------------------------------------

    if score < 30:

        level = "LOW"

    elif score < 60:

        level = "MEDIUM"

    else:

        level = "HIGH"

    # --------------------------------------------------------
    # What happens if user signs?
    # --------------------------------------------------------

    if function_name == "approve":

        if amount is not None:

            MAX_UINT256 = (2 ** 256) - 1

            if amount >= MAX_UINT256:

                impact = (
                    "Signing this transaction can give the spender "
                    "permission to spend an unlimited amount of your "
                    "tokens."
                )

            else:

                impact = (
                    f"Signing this transaction allows the spender "
                    f"to use approximately {amount} token units."
                )

        else:

            impact = (
                "Signing this transaction changes a token spending "
                "permission."
            )

    elif function_name == "transfer":

        impact = (
            "Signing this transaction sends tokens to the specified "
            "recipient."
        )

    elif function_name == "transferFrom":

        impact = (
            "Signing this transaction may move tokens from another "
            "address if the required allowance exists."
        )

    elif eth_value > 0:

        impact = (
            f"Signing this transaction can transfer "
            f"{eth_value:.4f} ETH to the destination."
        )

    elif function_name == "Unknown":

        impact = (
            "The transaction contains an unidentified function. "
            "Review the destination and calldata carefully before signing."
        )

    else:

        impact = (
            "Signing this transaction will execute the requested "
            "smart-contract function."
        )

    # --------------------------------------------------------
    # Explanation
    # --------------------------------------------------------

    if flags:

        explanation = (
            f"SafeSign identified {len(flags)} security signal(s). "
            f"The calculated risk is {level} with a score of {score}/100."
        )

    else:

        explanation = (
            f"No major warning signals were detected. "
            f"The calculated risk is {level} with a score of {score}/100."
        )

    return {
        "risk_score": score,
        "risk_level": level,
        "flags": flags,
        "explanation": explanation,
        "sign_impact": impact,
        "decoded": decoded,
    }


# ============================================================
# TRANSACTION ANALYSIS
# ============================================================

def analyze_transaction(payload):

    payload = payload or {}

    to_address = payload.get(
        "to"
    )

    data = payload.get(
        "data",
        "0x"
    )

    value = payload.get(
        "value",
        "0"
    )

    if data is None:
        data = "0x"

    decoded = decode_erc20_transaction(
        data
    )

    analysis = calculate_risk(
        to_address,
        data,
        value,
        decoded
    )

    # Add useful metadata
    analysis["to"] = to_address
    analysis["value"] = str(value)
    analysis["valueEth"] = wei_to_eth(value)

    return analysis


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    try:

        chain_id = w3.eth.chain_id

    except Exception:

        chain_id = None

    try:

        block = w3.eth.block_number

    except Exception:

        block = None

    database_status = "sqlite"

    ai_enabled = bool(
        AI_API_KEY
    )

    return jsonify(
        {
            "ok": True,
            "service": "SafeSign",
            "chainId": chain_id,
            "block": block,
            "database": database_status,
            "ai": ai_enabled,
            "wallet": (
                account.address
                if account
                else None
            ),
        }
    )


# ============================================================
# ANALYZE ENDPOINT
# ============================================================

@app.post("/analyze")
def analyze():

    try:

        payload = request.get_json(
            silent=True
        ) or {}

        result = analyze_transaction(
            payload
        )

        return jsonify(
            {
                "ok": True,
                **result,
            }
        )

    except Exception as exc:

        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500


# ============================================================
# AI EXPLANATION
# ============================================================

def build_ai_prompt(payload, analysis):

    return f"""
You are SafeSign, a Web3 transaction security assistant.

Explain a blockchain transaction to a beginner before they sign it.

Transaction:
{json.dumps(payload, indent=2)}

Security analysis:
{json.dumps(analysis, indent=2)}

Give a concise explanation covering:

1. What this transaction is doing.
2. What the user gives permission to do.
3. The main security concerns.
4. Whether the user should be cautious.
5. A simple final recommendation.

Do not claim that a transaction is guaranteed safe.
Do not invent contract information.
"""


@app.post("/ask")
def ask_ai():

    payload = request.get_json(
        silent=True
    ) or {}

    analysis = analyze_transaction(
        payload
    )

    # --------------------------------------------------------
    # Deterministic fallback
    # --------------------------------------------------------

    if not AI_API_KEY:

        level = analysis["risk_level"]
        score = analysis["risk_score"]
        flags = analysis["flags"]
        impact = analysis["sign_impact"]

        if flags:

            warning_text = " ".join(
                flags
            )

        else:

            warning_text = (
                "No major warning signals were detected."
            )

        explanation = (
            f"SafeSign classified this transaction as {level} "
            f"risk with a score of {score}/100. "
            f"{warning_text} "
            f"What happens if you sign: {impact}"
        )

        return jsonify(
            {
                "ok": True,
                "ai": False,
                "provider": "deterministic",
                "answer": explanation,
                "analysis": analysis,
            }
        )

    # --------------------------------------------------------
    # External AI provider
    # --------------------------------------------------------

    try:

        prompt = build_ai_prompt(
            payload,
            analysis
        )

        response = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={
                "Authorization": (
                    f"Bearer {AI_API_KEY}"
                ),
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are SafeSign, a Web3 "
                            "transaction security assistant."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.2,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        answer = (
            data["choices"][0]["message"]["content"]
        )

        return jsonify(
            {
                "ok": True,
                "ai": True,
                "provider": "external",
                "answer": answer,
                "analysis": analysis,
            }
        )

    except Exception as exc:

        return jsonify(
            {
                "ok": True,
                "ai": False,
                "provider": "deterministic-fallback",
                "answer": (
                    "The external AI provider could not be reached. "
                    "SafeSign's built-in transaction risk analysis "
                    "is still available."
                ),
                "error": str(exc),
                "analysis": analysis,
            }
        )


# ============================================================
# SAVE TRANSACTION
# ============================================================

@app.post("/transactions")
def save_transaction():

    payload = request.get_json(
        silent=True
    ) or {}

    wallet = payload.get(
        "wallet"
    )

    chain_id = payload.get(
        "chainId",
        11155111
    )

    contract_address = payload.get(
        "to"
    )

    function_name = payload.get(
        "function"
    )

    token_address = payload.get(
        "tokenAddress"
    )

    amount = payload.get(
        "value",
        "0"
    )

    risk_score = payload.get(
        "riskScore",
        0
    )

    risk_level = payload.get(
        "riskLevel"
    )

    flags = payload.get(
        "flags",
        []
    )

    explanation = payload.get(
        "explanation"
    )

    status = payload.get(
        "status",
        "signed"
    )

    # Make sure score is an integer
    try:

        risk_score = int(
            risk_score or 0
        )

    except (
        TypeError,
        ValueError
    ):

        risk_score = 0

    # Make sure flags are JSON serializable
    if not isinstance(
        flags,
        list
    ):

        flags = [
            str(flags)
        ]

    conn = db_connection()

    cursor = conn.execute(
        """
        INSERT INTO transactions (
            wallet_address,
            chain_id,
            contract_address,
            function_name,
            token_address,
            amount,
            risk_score,
            risk_level,
            flags,
            explanation,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wallet,
            chain_id,
            contract_address,
            function_name,
            token_address,
            str(amount),
            risk_score,
            risk_level,
            json.dumps(flags),
            explanation,
            status,
            now_iso(),
        ),
    )

    conn.commit()

    transaction_id = cursor.lastrowid

    conn.close()

    return jsonify(
        {
            "ok": True,
            "id": transaction_id,
        }
    ), 201


# ============================================================
# GET TRANSACTION HISTORY
# ============================================================

@app.get("/transactions")
def get_transactions():

    conn = db_connection()

    rows = conn.execute(
        """
        SELECT
            id,
            wallet_address,
            chain_id,
            contract_address,
            function_name,
            token_address,
            amount,
            risk_score,
            risk_level,
            flags,
            explanation,
            status,
            created_at
        FROM transactions
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    transactions = []

    for row in rows:

        transactions.append(
            {
                "id": row["id"],

                "wallet": row[
                    "wallet_address"
                ],

                "chainId": row[
                    "chain_id"
                ],

                "to": row[
                    "contract_address"
                ],

                "tokenAddress": row[
                    "token_address"
                ],

                "value": row[
                    "amount"
                ],

                "function": row[
                    "function_name"
                ],

                "riskLevel": row[
                    "risk_level"
                ],

                "riskScore": row[
                    "risk_score"
                ],

                "flags": safe_json_loads(
                    row["flags"],
                    []
                ),

                "explanation": row[
                    "explanation"
                ],

                "status": row[
                    "status"
                ],

                "createdAt": row[
                    "created_at"
                ],

                # The existing database does not
                # currently contain a tx_hash column.
                "txHash": None,

                "explorerUrl": None,
            }
        )

    return jsonify(
        {
            "ok": True,
            "transactions": transactions,
        }
    )


# ============================================================
# AI DECISION ENDPOINT
# ============================================================

@app.post("/ai/decide")
def ai_decide():

    payload = request.get_json(
        silent=True
    ) or {}

    analysis = analyze_transaction(
        payload
    )

    score = analysis[
        "risk_score"
    ]

    level = analysis[
        "risk_level"
    ]

    if level == "HIGH":

        decision = "REJECT"

    elif level == "MEDIUM":

        decision = "CAUTION"

    else:

        decision = "ALLOW"

    return jsonify(
        {
            "ok": True,
            "decision": decision,
            "riskScore": score,
            "riskLevel": level,
            "flags": analysis["flags"],
            "explanation": analysis["explanation"],
            "signImpact": analysis["sign_impact"],
        }
    )


# ============================================================
# BLOCKCHAIN RECORDS
# ============================================================

@app.get("/records")
def get_records():

    if not CONTRACT_ADDRESS:

        return jsonify(
            {
                "ok": False,
                "error": (
                    "CONTRACT_ADDRESS is not configured."
                ),
                "records": [],
            }
        )

    if not is_address(
        CONTRACT_ADDRESS
    ):

        return jsonify(
            {
                "ok": False,
                "error": (
                    "Configured CONTRACT_ADDRESS is invalid."
                ),
                "records": [],
            }
        )

    try:

        contract_address = checksum_address(
            CONTRACT_ADDRESS
        )

        code = w3.eth.get_code(
            contract_address
        )

        if not code:

            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "No contract code found at "
                        "CONTRACT_ADDRESS."
                    ),
                    "records": [],
                }
            )

        return jsonify(
            {
                "ok": True,
                "records": [],
                "message": (
                    "Contract is deployed. "
                    "Record retrieval depends on the "
                    "deployed contract ABI."
                ),
            }
        )

    except Exception as exc:

        return jsonify(
            {
                "ok": False,
                "error": str(exc),
                "records": [],
            }
        ), 500


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def root():

    return jsonify(
        {
            "service": "SafeSign",
            "status": "running",
            "message": (
                "SafeSign transaction security backend"
            ),
            "endpoints": [
                "/health",
                "/analyze",
                "/ask",
                "/ai/decide",
                "/transactions",
                "/records",
            ],
        }
    )


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@app.errorhandler(Exception)
def handle_error(error):

    print(
        "Backend error:",
        repr(error)
    )

    return jsonify(
        {
            "ok": False,
            "error": str(error),
        }
    ), 500


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("SafeSign Backend")
    print("=" * 60)

    print(
        "RPC:",
        RPC_URL
    )

    print(
        "Database:",
        DB_PATH
    )

    print(
        "AI enabled:",
        bool(AI_API_KEY)
    )

    print(
        "Wallet:",
        account.address
        if account
        else None
    )

    print(
        "Contract:",
        CONTRACT_ADDRESS
        if CONTRACT_ADDRESS
        else None
    )

    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )