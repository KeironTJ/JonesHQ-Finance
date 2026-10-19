(() => {
    'use strict';

    const buttons = document.querySelectorAll('[data-passkey-action]');
    const errorBox = document.querySelector('[data-passkey-error]');
    const showError = (message) => {
        errorBox.textContent = message;
        errorBox.classList.remove('d-none');
    };
    const decode = (value) => {
        const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
        return Uint8Array.from(atob(base64 + '='.repeat((4 - base64.length % 4) % 4)), (char) => char.charCodeAt(0));
    };
    const encode = (value) => {
        const bytes = new Uint8Array(value);
        return btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(''))
            .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    };
    const post = async (url, data) => {
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
            },
            body: JSON.stringify(data),
        });
        if (response.redirected) {
            window.location.assign(response.url);
            throw new Error('Please confirm your identity, then try again.');
        }
        if (!response.headers.get('content-type')?.includes('application/json')) {
            throw new Error(response.status === 429
                ? 'Too many attempts. Please wait and try again.'
                : 'The passkey request failed. Refresh the page and try again.');
        }
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'The passkey request failed. Please try again.');
        }
        return result;
    };

    if (!window.isSecureContext || !window.PublicKeyCredential || !navigator.credentials) {
        buttons.forEach((button) => { button.disabled = true; });
        showError('Passkeys need HTTPS (or localhost) and a compatible browser. You can still use your password and authenticator.');
        return;
    }

    buttons.forEach((button) => button.addEventListener('click', async () => {
        errorBox.classList.add('d-none');
        buttons.forEach((item) => { item.disabled = true; });
        try {
            const registering = button.dataset.passkeyAction === 'register';
            const data = registering
                ? { name: document.getElementById('passkey-name').value }
                : { remember: document.getElementById('remember')?.checked === true || button.dataset.remember === 'true' };
            const options = await post(button.dataset.optionsUrl, data);
            options.challenge = decode(options.challenge);
            if (registering) {
                options.user.id = decode(options.user.id);
                options.excludeCredentials?.forEach((item) => { item.id = decode(item.id); });
            } else {
                options.allowCredentials?.forEach((item) => { item.id = decode(item.id); });
            }
            const credential = registering
                ? await navigator.credentials.create({ publicKey: options })
                : await navigator.credentials.get({ publicKey: options });
            if (!credential) {
                throw new Error('No passkey was returned. Please try again.');
            }
            const response = { clientDataJSON: encode(credential.response.clientDataJSON) };
            if (registering) {
                response.attestationObject = encode(credential.response.attestationObject);
                response.transports = credential.response.getTransports?.() || [];
            } else {
                response.authenticatorData = encode(credential.response.authenticatorData);
                response.signature = encode(credential.response.signature);
                response.userHandle = credential.response.userHandle ? encode(credential.response.userHandle) : null;
            }
            const result = await post(button.dataset.verifyUrl, {
                id: credential.id, rawId: encode(credential.rawId), type: credential.type,
                authenticatorAttachment: credential.authenticatorAttachment,
                response, clientExtensionResults: credential.getClientExtensionResults(),
            });
            window.location.assign(result.redirect);
        } catch (error) {
            showError(error.name === 'NotAllowedError'
                ? 'The passkey prompt was cancelled or timed out. Try again or use your password and authenticator.'
                : error.message);
        } finally {
            buttons.forEach((item) => { item.disabled = false; });
        }
    }));
})();
