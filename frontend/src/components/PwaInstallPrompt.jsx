import React, { useState, useEffect } from 'react';

export default function PwaInstallPrompt({ inHeaderOnly = false }) {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isInstallable, setIsInstallable] = useState(false);
  const [isIos, setIsIos] = useState(false);
  const [showIosGuide, setShowIosGuide] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);

  useEffect(() => {
    // 1. Detect if already running in standalone PWA mode
    const standaloneMode =
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true;

    if (standaloneMode) {
      setIsStandalone(true);
      return;
    }

    // 2. Check if user dismissed previously in this session
    if (sessionStorage.getItem('lexai_pwa_dismissed') === '1') {
      setIsDismissed(true);
    }

    // 3. Detect iOS Safari
    const userAgent = window.navigator.userAgent.toLowerCase();
    const isIosDevice = /iphone|ipad|ipod/.test(userAgent);
    const isSafari = /safari/.test(userAgent) && !/chrome|crios|fxios/.test(userAgent);
    if (isIosDevice && isSafari) {
      setIsIos(true);
      setIsInstallable(true);
    }

    // 4. Capture standard Chromium / Android beforeinstallprompt event
    const handleBeforeInstall = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setIsInstallable(true);
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstall);

    // 5. Detect successful install
    window.addEventListener('appinstalled', () => {
      setIsInstallable(false);
      setDeferredPrompt(null);
      console.log('[PWA] LexAI installed successfully!');
    });

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
    };
  }, []);

  const handleInstallClick = async () => {
    if (isIos) {
      setShowIosGuide(true);
      return;
    }

    if (!deferredPrompt) {
      // Fallback for browsers where beforeinstallprompt isn't fired yet
      alert("To install LexAI:\n• Chrome/Edge: Click the install icon in the URL bar (⊕).\n• Android: Tap Menu (⋮) ➔ 'Install app' or 'Add to Home screen'.");
      return;
    }

    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      setIsInstallable(false);
    }
    setDeferredPrompt(null);
  };

  const handleDismiss = () => {
    setIsDismissed(true);
    sessionStorage.setItem('lexai_pwa_dismissed', '1');
  };

  // If already installed as app, do not render anything
  if (isStandalone) return null;

  // Header button variant
  if (inHeaderOnly) {
    if (!isInstallable) return null;
    return (
      <>
        <button
          type="button"
          className="btn-quiet header-tool-btn pwa-header-btn"
          onClick={handleInstallClick}
          title="Install LexAI App on your device"
          style={{
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2))',
            borderColor: 'rgba(99, 102, 241, 0.4)',
            color: '#a5b4fc',
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <span>📲</span>
          <span>Install App</span>
        </button>

        {showIosGuide && (
          <div className="pwa-ios-modal-backdrop" onClick={() => setShowIosGuide(false)}>
            <div className="pwa-ios-modal" onClick={(e) => e.stopPropagation()}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#f8fafc' }}>Install LexAI on iPhone / iPad</h3>
                <button
                  type="button"
                  onClick={() => setShowIosGuide(false)}
                  style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '1.2rem', cursor: 'pointer' }}
                >
                  ✕
                </button>
              </div>
              <p style={{ color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.5 }}>
                Apple Safari requires adding to home screen manually:
              </p>
              <ol style={{ color: '#e2e8f0', fontSize: '0.9rem', lineHeight: 1.8, paddingLeft: '20px' }}>
                <li>Tap the <strong>Share</strong> button <span style={{ fontSize: '1.1rem' }}>⎋</span> at the bottom of Safari.</li>
                <li>Scroll down and tap <strong>"Add to Home Screen"</strong> <span style={{ fontSize: '1.1rem' }}>➕</span>.</li>
                <li>Tap <strong>Add</strong> in the top-right corner.</li>
              </ol>
              <button
                type="button"
                className="btn-primary"
                onClick={() => setShowIosGuide(false)}
                style={{ width: '100%', marginTop: '14px', justifyContent: 'center' }}
              >
                Got it
              </button>
            </div>
          </div>
        )}
      </>
    );
  }

  // Floating Banner variant (on mobile/desktop if installable and not dismissed)
  if (!isInstallable || isDismissed) return null;

  return (
    <>
      <div className="pwa-banner-pill">
        <div className="pwa-banner-content">
          <div className="pwa-banner-icon">⚖️</div>
          <div className="pwa-banner-text">
            <strong>Install LexAI App</strong>
            <small>Instant access & offline support</small>
          </div>
        </div>
        <div className="pwa-banner-actions">
          <button type="button" className="pwa-install-btn" onClick={handleInstallClick}>
            Install
          </button>
          <button type="button" className="pwa-dismiss-btn" onClick={handleDismiss} title="Dismiss">
            ✕
          </button>
        </div>
      </div>

      {showIosGuide && (
        <div className="pwa-ios-modal-backdrop" onClick={() => setShowIosGuide(false)}>
          <div className="pwa-ios-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#f8fafc' }}>Install LexAI on iOS</h3>
              <button
                type="button"
                onClick={() => setShowIosGuide(false)}
                style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <p style={{ color: '#cbd5e1', fontSize: '0.9rem', lineHeight: 1.5 }}>
              To install on iPhone or iPad:
            </p>
            <ol style={{ color: '#e2e8f0', fontSize: '0.9rem', lineHeight: 1.8, paddingLeft: '20px' }}>
              <li>Tap the <strong>Share</strong> button <span style={{ fontSize: '1.1rem' }}>⎋</span> at the bottom of Safari.</li>
              <li>Scroll down and tap <strong>"Add to Home Screen"</strong> <span style={{ fontSize: '1.1rem' }}>➕</span>.</li>
              <li>Tap <strong>Add</strong> in the top-right corner.</li>
            </ol>
            <button
              type="button"
              className="btn-primary"
              onClick={() => setShowIosGuide(false)}
              style={{ width: '100%', marginTop: '14px', justifyContent: 'center' }}
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  );
}
