// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Scenarios} from "../harness/Scenarios.sol";

/// @notice Environment-driven scenario entry points executed by the HookLens backend:
///   forge test --match-contract <Contract> --fork-url <rpc> --fork-block-number <n>
/// Without HL_HOOK in the environment these tests are skipped.
contract FeeEscalationScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_feeEscalation() public {
        _requireConfigured();
        _runFeeEscalation(_envFee());
    }
}

contract WithdrawalFailureScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_withdrawalFailure() public {
        _requireConfigured();
        _runWithdrawal(_envWithdrawal());
    }
}

contract OracleFailureScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_oracleFailure() public {
        _requireConfigured();
        _runOracleFailure(_envOracle());
    }
}

contract AccountingInvariantScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_accounting() public {
        _requireConfigured();
        _runAccounting();
    }
}

contract AdminUpgradeScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_adminUpgrade() public {
        _requireConfigured();
        _runAdmin(_envAdmin());
    }
}

contract TransactionOrderingScenario is Scenarios {
    function setUp() public {
        _loadEnvConfig();
    }

    function test_ordering() public {
        _requireConfigured();
        _runOrdering();
    }
}
