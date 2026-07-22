"""Venue adapters for RWOO execution.

Each adapter implements the ``rwoo.execution.ExecutionAdapter`` protocol. This
package is deliberately import-light and holds no signing secrets. A funded
signer, if one ever exists, is constructed by the operator in a separate,
isolated, non-root process and injected — never imported here.
"""
