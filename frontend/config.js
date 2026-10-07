// ============================================================
// SafeSign configuration
// ============================================================

const ACTIVE_NETWORK = "sepolia";

// The original starter contract is NOT required for the
// transaction analyzer. Keep this address if you have not
// deployed a replacement contract yet.
const CONTRACT_ADDRESS =
  "0x0000000000000000000000000000000000000000";

const BACKEND_URL = "http://localhost:5000";

// Kept for compatibility with the INNOBLOCK starter.
const CONTRACT_ABI = [
  "function store(bytes32 hash) returns (uint256 id)",
  "function verify(uint256 id, bytes32 hash) view returns (bool)",
  "function records(uint256 id) view returns (bytes32)",
  "function count() view returns (uint256)",
  "event RecordStored(uint256 indexed id, bytes32 hash, address indexed by, uint256 time)",
];

const NETWORKS = {
  sepolia: {
    name: "Ethereum Sepolia",
    chainId: 11155111,
    rpcUrl: "https://ethereum-sepolia-rpc.publicnode.com",
    explorer: "https://sepolia.etherscan.io",
    currency: "ETH",
  },

  baseSepolia: {
    name: "Base Sepolia",
    chainId: 84532,
    rpcUrl: "https://base-sepolia-rpc.publicnode.com",
    explorer: "https://sepolia.basescan.org",
    currency: "ETH",
  },

  polygonAmoy: {
    name: "Polygon Amoy",
    chainId: 80002,
    rpcUrl: "https://polygon-amoy-bor-rpc.publicnode.com",
    explorer: "https://amoy.polygonscan.com",
    currency: "POL",
  },

  arbitrumSepolia: {
    name: "Arbitrum Sepolia",
    chainId: 421614,
    rpcUrl: "https://sepolia.arbiscan.io",
    explorer: "https://sepolia.arbiscan.io",
    currency: "ETH",
  },

  optimismSepolia: {
    name: "OP Sepolia",
    chainId: 11155420,
    rpcUrl: "https://optimism-sepolia.etherscan.io",
    explorer: "https://sepolia-optimism.etherscan.io",
    currency: "ETH",
  },
};