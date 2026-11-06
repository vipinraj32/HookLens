// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title HookProxy
/// @notice HOOKLENS TEST FIXTURE. Minimal EIP-1967 upgradeable proxy. The proxy address
///         (mined for hook permission bits) is the hook registered with the PoolManager,
///         while logic lives in an implementation contract that its admin can replace.
contract HookProxy {
    /// @dev bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1)
    bytes32 internal constant IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;
    /// @dev bytes32(uint256(keccak256("eip1967.proxy.admin")) - 1)
    bytes32 internal constant ADMIN_SLOT = 0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103;

    event Upgraded(address indexed implementation);
    event AdminChanged(address previousAdmin, address newAdmin);

    error NotAdmin();
    error NotAContract();

    constructor(address implementation, address admin, bytes memory initData) {
        _setImplementation(implementation);
        _setAdmin(admin);
        if (initData.length > 0) {
            (bool ok, bytes memory ret) = implementation.delegatecall(initData);
            if (!ok) {
                assembly {
                    revert(add(ret, 32), mload(ret))
                }
            }
        }
    }

    function proxyAdmin() external view returns (address) {
        return _admin();
    }

    function proxyImplementation() external view returns (address i) {
        bytes32 slot = IMPLEMENTATION_SLOT;
        assembly {
            i := sload(slot)
        }
    }

    function upgradeTo(address newImplementation) external {
        if (msg.sender != _admin()) revert NotAdmin();
        _setImplementation(newImplementation);
    }

    function changeProxyAdmin(address newAdmin) external {
        if (msg.sender != _admin()) revert NotAdmin();
        _setAdmin(newAdmin);
    }

    function _admin() internal view returns (address a) {
        bytes32 slot = ADMIN_SLOT;
        assembly {
            a := sload(slot)
        }
    }

    function _setImplementation(address impl) internal {
        if (impl.code.length == 0) revert NotAContract();
        bytes32 slot = IMPLEMENTATION_SLOT;
        assembly {
            sstore(slot, impl)
        }
        emit Upgraded(impl);
    }

    function _setAdmin(address newAdmin) internal {
        emit AdminChanged(_admin(), newAdmin);
        bytes32 slot = ADMIN_SLOT;
        assembly {
            sstore(slot, newAdmin)
        }
    }

    fallback() external payable {
        bytes32 slot = IMPLEMENTATION_SLOT;
        assembly {
            let impl := sload(slot)
            calldatacopy(0, 0, calldatasize())
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}
