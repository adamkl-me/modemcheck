/**
 * Error handling utilities for ModemCheck web UI.
 *
 * This module provides user-friendly error message extraction
 * from API responses, supporting both ModemCheckError format
 * and legacy HTTPException format.
 */

/**
 * User-friendly error messages for common error codes.
 */
const ERROR_CODE_MESSAGES = {
    'AUTHENTICATION_ERROR': 'Please check your credentials and try again.',
    'ACCOUNT_LOCKED': 'Account temporarily locked due to too many failed attempts.',
    'AUTHORIZATION_ERROR': 'You do not have permission to perform this action.',
    'INSUFFICIENT_PERMISSIONS': 'You do not have permission to perform this action.',
    'PASSWORD_CHANGE_REQUIRED': 'Please change your password to continue.',
    'VALIDATION_ERROR': 'Please check your input and try again.',
    'INVALID_PARAMETER': 'Please check your input and try again.',
    'MISSING_PARAMETER': 'Required information is missing.',
    'NOT_FOUND': 'The requested item was not found.',
    'CONFLICT': 'This operation conflicts with existing data.',
    'DUPLICATE_RESOURCE': 'This item already exists.',
    'RATE_LIMIT_EXCEEDED': 'Too many requests. Please wait a moment.',
    'FILE_TOO_LARGE': 'The file is too large.',
    'ZIP_BOMB_DETECTED': 'The file appears to be invalid or too large.',
    'INTERNAL_SERVER_ERROR': 'Something went wrong. Please try again later.',
    'SERVICE_UNAVAILABLE': 'Service temporarily unavailable. Please try again later.',
};

/**
 * User-friendly messages for HTTP status codes.
 */
const STATUS_CODE_MESSAGES = {
    400: 'Invalid request. Please check your input.',
    401: 'Please log in to continue.',
    403: 'You do not have permission to perform this action.',
    404: 'The requested item was not found.',
    409: 'This operation conflicts with existing data.',
    413: 'The uploaded content is too large.',
    422: 'Please check your input and try again.',
    429: 'Too many requests. Please wait a moment.',
    500: 'Something went wrong. Please try again later.',
    503: 'Service temporarily unavailable.',
};

/**
 * Extract user-friendly error message from API response.
 *
 * Handles both ModemCheckError format (error.message) and
 * legacy HTTPException format (detail string).
 *
 * @param {Response} response - Fetch Response object
 * @param {Object} data - Parsed JSON response body
 * @returns {string} User-friendly error message
 */
function getErrorMessage(response, data) {
    // ModemCheckError format (preferred)
    if (data && data.error && data.error.message) {
        return data.error.message;
    }

    // Legacy HTTPException format with detail string
    if (data && data.detail) {
        if (typeof data.detail === 'string') {
            return data.detail;
        }
        // Pydantic validation errors (array of error objects)
        if (Array.isArray(data.detail)) {
            return data.detail
                .map(err => err.msg || err.message || JSON.stringify(err))
                .join(', ');
        }
        // Nested detail object
        if (data.detail.message) {
            return data.detail.message;
        }
    }

    // Simple error string
    if (data && data.error && typeof data.error === 'string') {
        return data.error;
    }

    // Fallback to status-based message
    return getGenericErrorMessage(response ? response.status : 500);
}

/**
 * Get generic user-friendly message for HTTP status code.
 *
 * @param {number} statusCode - HTTP status code
 * @returns {string} User-friendly error message
 */
function getGenericErrorMessage(statusCode) {
    return STATUS_CODE_MESSAGES[statusCode] || 'An error occurred. Please try again.';
}

/**
 * Get user-friendly message for a ModemCheckError code.
 *
 * @param {string} errorCode - Error code from ModemCheckError
 * @returns {string|null} User-friendly message or null if not found
 */
function getMessageForErrorCode(errorCode) {
    return ERROR_CODE_MESSAGES[errorCode] || null;
}

/**
 * Extract error details from API response.
 * Useful for logging or advanced error handling.
 *
 * @param {Object} data - Parsed JSON response body
 * @returns {Object|null} Error details object or null
 */
function getErrorDetails(data) {
    if (data && data.error && typeof data.error === 'object') {
        return {
            errorId: data.error.error_id,
            code: data.error.code,
            timestamp: data.error.timestamp,
            details: data.error.details
        };
    }
    return null;
}

/**
 * Get error code from API response.
 *
 * @param {Object} data - Parsed JSON response body
 * @returns {string|null} Error code or null
 */
function getErrorCode(data) {
    if (data && data.error && data.error.code) {
        return data.error.code;
    }
    return null;
}

/**
 * Check if error is an account lockout.
 *
 * @param {Object} data - Parsed JSON response body
 * @returns {boolean} True if account is locked
 */
function isAccountLocked(data) {
    return getErrorCode(data) === 'ACCOUNT_LOCKED';
}

/**
 * Get lockout remaining time from error response.
 *
 * @param {Object} data - Parsed JSON response body
 * @returns {number|null} Remaining seconds or null
 */
function getLockoutRemainingSeconds(data) {
    if (data && data.error && data.error.details) {
        return data.error.details.remaining_seconds ||
               data.error.details.retry_after_seconds ||
               null;
    }
    return null;
}

/**
 * Format lockout message with remaining time.
 *
 * @param {Object} data - Parsed JSON response body
 * @returns {string} Formatted lockout message
 */
function formatLockoutMessage(data) {
    const seconds = getLockoutRemainingSeconds(data);
    if (seconds) {
        const minutes = Math.ceil(seconds / 60);
        return `Account temporarily locked. Please try again in ${minutes} minute${minutes !== 1 ? 's' : ''}.`;
    }
    return 'Account temporarily locked. Please try again later.';
}

/**
 * Process API error response and return appropriate message.
 * This is the main function to use in catch blocks.
 *
 * @param {Response} response - Fetch Response object
 * @param {Object} data - Parsed JSON response body (optional)
 * @returns {Promise<string>} User-friendly error message
 */
async function handleApiError(response, data = null) {
    // Parse response if data not provided
    if (!data && response) {
        try {
            data = await response.json();
        } catch (e) {
            // Response body already consumed or not JSON
            data = null;
        }
    }

    // Handle account lockout specially
    if (isAccountLocked(data)) {
        return formatLockoutMessage(data);
    }

    return getErrorMessage(response, data);
}
