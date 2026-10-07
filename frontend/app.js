// ============================================================
// SafeSign frontend
// ============================================================

const NETWORK =
  NETWORKS[ACTIVE_NETWORK] || NETWORKS.sepolia;

const CHAIN_ID_HEX =
  "0x" + NETWORK.chainId.toString(16);


// ============================================================
// STATE
// ============================================================

let provider = null;
let signer = null;
let currentAccount = null;

let currentTransaction = null;
let currentAnalysis = null;


// ============================================================
// HELPERS
// ============================================================

const $ = (id) =>
  document.getElementById(id);


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function shortAddress(address) {
  if (!address) return "-";

  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}


function txUrl(hash) {
  return `${NETWORK.explorer}/tx/${hash}`;
}


function setStatus(element, message, type = "") {
  if (!element) return;

  element.className = `status ${type}`;

  element.textContent = message;
}


function friendlyError(error) {

  if (error?.code === 4001) {
    return "You rejected the request in MetaMask.";
  }

  if (
    error?.code === "ACTION_REJECTED" ||
    error?.code === "ACTION_REJECTED"
  ) {
    return "You rejected the transaction.";
  }

  if (error?.code === -32002) {
    return "MetaMask already has a pending request. Open MetaMask.";
  }

  if (
    error?.code === "INSUFFICIENT_FUNDS"
  ) {
    return `Not enough test ${NETWORK.currency}.`;
  }

  return (
    error?.shortMessage ||
    error?.message ||
    "Something went wrong."
  );
}


async function api(path, options = {}) {

  let response;

  try {

    response = await fetch(
      `${BACKEND_URL}${path}`,
      {
        headers: {
          "Content-Type": "application/json",
        },

        ...options,
      }
    );

  } catch (error) {

    throw new Error(
      `Cannot reach backend at ${BACKEND_URL}. Make sure app.py is running.`
    );

  }

  const data =
    await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.error ||
      `Backend error ${response.status}`
    );
  }

  return data;
}


// ============================================================
// WALLET
// ============================================================

async function switchToNetwork() {

  if (!window.ethereum) {
    throw new Error(
      "MetaMask was not detected."
    );
  }

  try {

    await window.ethereum.request({
      method: "wallet_switchEthereumChain",

      params: [
        {
          chainId: CHAIN_ID_HEX,
        },
      ],
    });

  } catch (error) {

    // 4902 = network not added
    if (error.code === 4902) {

      await window.ethereum.request({
        method: "wallet_addEthereumChain",

        params: [
          {
            chainId: CHAIN_ID_HEX,

            chainName: NETWORK.name,

            nativeCurrency: {
              name: NETWORK.currency,
              symbol: NETWORK.currency,
              decimals: 18,
            },

            rpcUrls: [
              NETWORK.rpcUrl,
            ],

            blockExplorerUrls: [
              NETWORK.explorer,
            ],
          },
        ],
      });

    } else {
      throw error;
    }
  }
}


async function connectWallet() {

  try {

    if (!window.ethereum) {
      throw new Error(
        "MetaMask is not installed."
      );
    }

    await window.ethereum.request({
      method: "eth_requestAccounts",
    });

    await switchToNetwork();

    provider =
      new ethers.BrowserProvider(
        window.ethereum
      );

    signer =
      await provider.getSigner();

    currentAccount =
      await signer.getAddress();

    updateWalletUI();

    const status = $("connect-status");

    setStatus(
      status,
      "Wallet connected.",
      "confirmed"
    );

  } catch (error) {

    setStatus(
      $("connect-status"),
      friendlyError(error),
      "failed"
    );

  }
}


async function updateWalletUI() {

  if (!provider || !currentAccount) {
    return;
  }

  $("wallet-address").textContent =
    shortAddress(currentAccount);

  try {

    const balance =
      await provider.getBalance(
        currentAccount
      );

    $("wallet-balance").textContent =
      `${Number(
        ethers.formatEther(balance)
      ).toFixed(4)} ${NETWORK.currency}`;

  } catch {
    $("wallet-balance").textContent =
      "-";
  }
}


// ============================================================
// TRANSACTION DECODING
// ============================================================

const ERC20_INTERFACE =
  new ethers.Interface([
    "function approve(address spender,uint256 amount)",
    "function transfer(address to,uint256 amount)",
    "function transferFrom(address from,address to,uint256 amount)",
    "function increaseAllowance(address spender,uint256 addedValue)",
    "function decreaseAllowance(address spender,uint256 subtractedValue)",
  ]);


function decodeTransaction(
  to,
  data,
  value
) {

  const result = {
    function: "Native ETH Transfer",
    args: {},
    spender: null,
    amount: null,
    amountIsUnlimited: false,
  };


  if (
    !data ||
    data === "0x"
  ) {
    return result;
  }


  try {

    const parsed =
      ERC20_INTERFACE.parseTransaction({
        data,
        value: BigInt(value || "0"),
      });

    if (!parsed) {
      result.function =
        "Unknown Function";

      return result;
    }


    result.function =
      parsed.name;


    if (parsed.name === "approve") {

      const spender =
        parsed.args[0];

      const amount =
        parsed.args[1];

      result.spender =
        spender;

      result.amount =
        amount.toString();

      result.amountIsUnlimited =
        amount >=
        ethers.MaxUint256 - 1000n;

      result.args = {
        spender,
        amount:
          result.amountIsUnlimited
            ? "UNLIMITED"
            : amount.toString(),
      };

    } else if (
      parsed.name === "transfer"
    ) {

      result.args = {
        to: parsed.args[0],
        amount:
          parsed.args[1].toString(),
      };

    } else if (
      parsed.name === "transferFrom"
    ) {

      result.args = {
        from: parsed.args[0],
        to: parsed.args[1],
        amount:
          parsed.args[2].toString(),
      };

    } else if (
      parsed.name === "increaseAllowance"
    ) {

      result.args = {
        spender: parsed.args[0],
        amount:
          parsed.args[1].toString(),
      };

    } else if (
      parsed.name === "decreaseAllowance"
    ) {

      result.args = {
        spender: parsed.args[0],
        amount:
          parsed.args[1].toString(),
      };

    }

  } catch {

    result.function =
      "Unknown Function";
  }


  return result;
}


// ============================================================
// UPDATE TRANSACTION PREVIEW
// ============================================================

function updateTransactionPreview() {

  const to =
    $("tx-contract").value.trim();

  const data =
    $("tx-data").value.trim() || "0x";

  const value =
    $("tx-value").value.trim() || "0";


  const decoded =
    decodeTransaction(
      to,
      data,
      value
    );


  $("decoded-function").textContent =
    decoded.function;

  $("decoded-contract").textContent =
    to || "-";


  let ethDisplay = "0 ETH";

  try {

    ethDisplay =
      `${ethers.formatEther(
        value || "0"
      )} ETH`;

  } catch {
    ethDisplay = "0 ETH";
  }

  $("tx-display-value").textContent =
    ethDisplay;


  if (
    Object.keys(decoded.args).length === 0
  ) {

    $("decoded-args").textContent =
      "No arguments";

  } else {

    $("decoded-args").textContent =
      JSON.stringify(
        decoded.args,
        null,
        2
      );

  }
}


// ============================================================
// PREPARE UNLIMITED APPROVAL DEMO
// ============================================================

function prepareApprovalDemo() {

  const token =
    $("token-address").value.trim();

  const spender =
    $("spender-address").value.trim();


  if (!ethers.isAddress(token)) {

    setStatus(
      $("analysis-status"),
      "Enter a valid token contract address.",
      "failed"
    );

    return;
  }


  if (!ethers.isAddress(spender)) {

    setStatus(
      $("analysis-status"),
      "Enter a valid spender address.",
      "failed"
    );

    return;
  }


  const iface =
    new ethers.Interface([
      "function approve(address spender,uint256 amount)",
    ]);


  const calldata =
    iface.encodeFunctionData(
      "approve",
      [
        spender,
        ethers.MaxUint256,
      ]
    );


  $("tx-contract").value =
    token;

  $("tx-data").value =
    calldata;

  $("tx-value").value =
    "0";


  updateTransactionPreview();


  setStatus(
    $("analysis-status"),
    "Unlimited approval prepared. Click Analyze transaction.",
    "confirmed"
  );
}


// ============================================================
// BUILD CURRENT TRANSACTION
// ============================================================

function getCurrentTransaction() {

  const to =
    $("tx-contract").value.trim();

  const data =
    $("tx-data").value.trim() || "0x";

  const value =
    $("tx-value").value.trim() || "0";


  if (!ethers.isAddress(to)) {
    throw new Error(
      "Enter a valid destination contract address."
    );
  }


  let valueWei;

  try {

    // User enters ETH, not wei.
    valueWei =
      ethers.parseEther(value);

  } catch {

    throw new Error(
      "ETH value must be a valid number."
    );

  }


  return {
    from:
      currentAccount || null,

    to,

    data,

    value:
      valueWei.toString(),
  };
}


// ============================================================
// ANALYZE
// ============================================================

async function analyzeTransaction() {

  try {

    currentTransaction =
      getCurrentTransaction();


    setStatus(
      $("analysis-status"),
      "Analyzing transaction...",
      "pending"
    );


    const result =
      await api(
        "/analyze",
        {
          method: "POST",

          body: JSON.stringify(
            currentTransaction
          ),
        }
      );


    currentAnalysis =
      result;


    updateTransactionPreview();

    displayRiskAnalysis(result);


    setStatus(
      $("analysis-status"),
      "Security analysis complete.",
      "confirmed"
    );

  } catch (error) {

    setStatus(
      $("analysis-status"),
      friendlyError(error),
      "failed"
    );

  }
}


// ============================================================
// RISK DISPLAY
// ============================================================

function displayRiskAnalysis(result) {

  $("risk-card")
    .classList
    .remove("hidden");


  const level =
    result.risk_level || "UNKNOWN";

  const score =
    Number(result.risk_score || 0);


  $("risk-level").textContent =
    level;

  $("risk-score").textContent =
    `${score}/100`;


  const levelLower =
    level.toLowerCase();


  if (levelLower === "high") {

    $("risk-level").style.color =
      "var(--bad)";

  } else if (
    levelLower === "medium"
  ) {

    $("risk-level").style.color =
      "var(--pending)";

  } else {

    $("risk-level").style.color =
      "var(--accent)";
  }


  $("risk-meter-fill").style.width =
    `${score}%`;


  const flags =
    result.flags || [];


  if (!flags.length) {

    $("risk-flags").innerHTML =
      `
      <div class="flag low">
        <strong>No major warning signals</strong>
        <p>
          SafeSign did not detect a major risk indicator.
        </p>
      </div>
      `;

  } else {

    $("risk-flags").innerHTML =
      flags
        .map((flag) => {

          const severity =
            String(
              flag.severity || "MEDIUM"
            ).toLowerCase();

          return `
            <div class="flag ${escapeHtml(severity)}">
              <strong>
                ${escapeHtml(flag.title)}
              </strong>

              <p>
                ${escapeHtml(flag.message)}
              </p>
            </div>
          `;

        })
        .join("");
  }


  $("sign-impact").textContent =
    result.sign_impact ||
    "SafeSign could not determine the exact impact.";


  $("ai-explanation").textContent =
    result.explanation ||
    "No explanation available.";
}


// ============================================================
// ASK SAFE SIGN
// ============================================================

async function getAIExplanation() {

  if (!currentAnalysis) {
    return;
  }

  try {

    const result =
      await api(
        "/ask",
        {
          method: "POST",

          body: JSON.stringify({
            question:
              "Explain this transaction to a beginner.",
            context:
              currentAnalysis,
          }),
        }
      );


    if (result.answer) {

      $("ai-explanation").textContent =
        result.answer;

    }

  } catch {
    // The deterministic explanation is already displayed.
  }
}


// ============================================================
// CONTINUE TO METAMASK
// ============================================================

async function continueToMetaMask() {

  try {

    if (!window.ethereum) {
      throw new Error(
        "MetaMask is not installed."
      );
    }


    if (!signer) {

      await connectWallet();

      if (!signer) {
        return;
      }
    }


    if (!currentTransaction) {

      currentTransaction =
        getCurrentTransaction();
    }


    if (!currentAnalysis) {

      await analyzeTransaction();

      if (!currentAnalysis) {
        return;
      }
    }


    const score =
      Number(
        currentAnalysis.risk_score || 0
      );


    if (score >= 60) {

      const confirmed =
        window.confirm(
          "SafeSign has detected HIGH RISK. Do you still want to send this transaction to MetaMask?"
        );

      if (!confirmed) {
        return;
      }
    }


    const tx = {

      to:
        currentTransaction.to,

      data:
        currentTransaction.data,

      value:
        BigInt(
          currentTransaction.value
        ),
    };


    setStatus(
      $("analysis-status"),
      "Waiting for MetaMask confirmation...",
      "pending"
    );


    const response =
      await signer.sendTransaction(tx);


    setStatus(
      $("analysis-status"),
      `Transaction submitted: ${response.hash}`,
      "pending"
    );


    const receipt =
      await response.wait();


    if (!receipt) {
      throw new Error(
        "Transaction receipt was not returned."
      );
    }


    setStatus(
      $("analysis-status"),
      "Transaction confirmed.",
      "confirmed"
    );


    const link =
      document.createElement("a");

    link.href =
      txUrl(response.hash);

    link.target =
      "_blank";

    link.rel =
      "noopener";

    link.textContent =
      " View on Sepolia Etherscan ↗";


    $("analysis-status")
      .appendChild(
        link
      );


    await saveTransaction(
      response.hash
    );

    await loadHistory();

    await updateWalletUI();

  } catch (error) {

    setStatus(
      $("analysis-status"),
      friendlyError(error),
      "failed"
    );
  }
}


// ============================================================
// SAVE TRANSACTION
// ============================================================

async function saveTransaction(
  txHash
) {

  if (!currentAnalysis) {
    return;
  }


  try {

    await api(
      "/transactions",
      {
        method: "POST",

        body: JSON.stringify({

          wallet:
            currentAccount,

          txHash,

          to:
            currentTransaction.to,

          value:
            currentTransaction.value,

          function:
            currentAnalysis.decoded?.function ||
            "Unknown Function",

          riskLevel:
            currentAnalysis.risk_level,

          riskScore:
            currentAnalysis.risk_score,

          flags:
            currentAnalysis.flags || [],

          explanation:
            currentAnalysis.explanation || "",
        }),
      }
    );

  } catch (error) {

    console.warn(
      "Could not save history:",
      error
    );
  }
}


// ============================================================
// HISTORY
// ============================================================

async function loadHistory() {

  const container =
    $("transaction-history");


  container.innerHTML =
    "Loading...";


  try {

    const result =
      await api(
        "/transactions"
      );


    const transactions =
      result.transactions || [];


    if (!transactions.length) {

      container.textContent =
        "No reviewed transactions yet.";

      return;
    }


    container.innerHTML =
      transactions
        .map((tx) => {

          const level =
            String(
              tx.riskLevel || "UNKNOWN"
            ).toLowerCase();


          return `
            <div class="history-row">

              <div>

                <div class="history-function">
                  ${escapeHtml(
                    tx.function || "Unknown Function"
                  )}
                </div>

                <div class="history-meta">
                  ${escapeHtml(
                    shortAddress(tx.to)
                  )}
                </div>

              </div>


              <div
                class="history-risk ${escapeHtml(level)}"
              >
                ${escapeHtml(
                  tx.riskLevel || "UNKNOWN"
                )}
                ${Number(
                  tx.riskScore || 0
                )}/100
              </div>


              <div class="history-meta">
                ${escapeHtml(
                  shortAddress(tx.txHash)
                )}
              </div>


              <a
                href="${escapeHtml(
                  txUrl(tx.txHash)
                )}"
                target="_blank"
                rel="noopener"
              >
                Explorer ↗
              </a>

            </div>
          `;

        })
        .join("");

  } catch (error) {

    container.textContent =
      error.message;
  }
}


// ============================================================
// EVENTS
// ============================================================

function setupEvents() {

  $("connect-btn")
    .addEventListener(
      "click",
      connectWallet
    );


  $("approval-demo-btn")
    .addEventListener(
      "click",
      prepareApprovalDemo
    );


  $("analyze-btn")
    .addEventListener(
      "click",
      analyzeTransaction
    );


  $("continue-btn")
    .addEventListener(
      "click",
      continueToMetaMask
    );


  $("reject-btn")
    .addEventListener(
      "click",
      () => {

        currentTransaction = null;
        currentAnalysis = null;

        $("risk-card")
          .classList
          .add("hidden");

        setStatus(
          $("analysis-status"),
          "Transaction rejected by user.",
          "failed"
        );
      }
    );


  $("history-btn")
    .addEventListener(
      "click",
      loadHistory
    );


  $("tx-contract")
    .addEventListener(
      "input",
      updateTransactionPreview
    );


  $("tx-data")
    .addEventListener(
      "input",
      updateTransactionPreview
    );


  $("tx-value")
    .addEventListener(
      "input",
      updateTransactionPreview
    );


  if (window.ethereum) {

    window.ethereum.on(
      "accountsChanged",
      () => {
        location.reload();
      }
    );


    window.ethereum.on(
      "chainChanged",
      () => {
        location.reload();
      }
    );
  }
}


// ============================================================
// INIT
// ============================================================

function init() {

  $("network-badge").textContent =
    NETWORK.name;


  if (
    !window.ethereum
  ) {

    $("setup-warning")
      .textContent =
      "MetaMask was not detected. Install MetaMask to sign transactions.";

    $("setup-warning")
      .classList
      .remove("hidden");
  }


  setupEvents();

  updateTransactionPreview();

  loadHistory();
}


init();