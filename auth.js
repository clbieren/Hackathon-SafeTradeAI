/**
 * SafeTrade AI - Kimlik Doğrulama Yöneticisi
 * Bu modül, JWT token yönetimini ve frontend auth state'ini kontrol eder.
 */

const AuthManager = {
    TOKEN_KEY: 'safetrade_token',

    /**
     * @returns {string|null} Mevcut token veya null
     */
    getToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    /**
     * @param {string} token - Kaydedilecek JWT token
     */
    setToken(token) {
        localStorage.setItem(this.TOKEN_KEY, token);
    },

    /**
     * Kullanıcıyı sistemden çıkarır ve token'ı temizler
     */
    logout() {
        localStorage.removeItem(this.TOKEN_KEY);
        window.location.href = 'login.html';
    },

    /**
     * Fetch için yetkilendirme header'larını döner
     * @returns {Object} Headers objesi
     */
    getAuthHeaders() {
        const token = this.getToken();
        if (!token) return {};
        return {
            'Authorization': `Bearer ${token}`
        };
    },

    /**
     * Kullanıcının giriş yapıp yapmadığını kontrol eder
     * @returns {boolean}
     */
    isAuthenticated() {
        return !!this.getToken();
    },

    /**
     * Korumalı sayfalarda auth kontrolü yapar. Token yoksa login sayfasına atar.
     */
    requireAuth() {
        if (!this.isAuthenticated()) {
            window.location.href = 'login.html';
        }
    },

    /**
     * Korumasız (public) veya zaten giriş yapmış kullanıcının login sayfasına gitmesini engeller.
     */
    redirectIfAuthenticated() {
        if (this.isAuthenticated()) {
            window.location.href = 'discovery.html';
        }
    },

    /**
     * Auth aware fetch wrapper. 401 Unauthorized dönerse otomatik logout yapar.
     * 
     * @param {string} url 
     * @param {Object} options 
     * @returns {Promise<Response>}
     */
    async fetch(url, options = {}) {
        const headers = {
            ...options.headers,
            ...this.getAuthHeaders()
        };

        const config = {
            ...options,
            headers
        };

        try {
            const response = await fetch(url, config);
            if (response.status === 401) {
                // Token geçersiz veya süresi dolmuş
                console.warn("Yetkisiz erişim algılandı. Oturum sonlandırılıyor.");
                this.logout();
                return response;
            }
            return response;
        } catch (error) {
            console.error("Auth-aware fetch hatası:", error);
            throw error;
        }
    },

    /**
     * Mevcut kullanıcının profil bilgilerini API'den getirir
     * @returns {Promise<Object|null>} Kullanıcı bilgisi veya null
     */
    async getUserInfo() {
        if (!this.isAuthenticated()) return null;
        
        // API_BASE app.js'den alınır veya default
        const apiBase = typeof API_BASE !== 'undefined' ? API_BASE : "";
        
        try {
            const response = await fetch(`${apiBase}/auth/me`, {
                headers: this.getAuthHeaders()
            });
            if (response.ok) {
                return await response.json();
            }
            return null;
        } catch (e) {
            return null;
        }
    },
    
    /**
     * Sayfadaki Navbar'ı kullanıcı bilgilerine göre günceller
     */
    async updateNavbar() {
        const navActions = document.querySelector('.nav-actions');
        if (!navActions) return;

        if (this.isAuthenticated()) {
            // Kullanıcı giriş yapmış, menüyü profil + çıkış butonu ile değiştir
            const user = await this.getUserInfo();
            const displayName = user ? user.full_name : "Kullanıcı";
            const initial = displayName.charAt(0).toUpperCase();

            navActions.innerHTML = `
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <div style="display:flex; align-items:center; gap:0.5rem; background:rgba(255,255,255,0.05); padding: 0.3rem 1rem 0.3rem 0.3rem; border-radius:100px; border:1px solid var(--glass-border)">
                        <div style="width:28px; height:28px; background:linear-gradient(135deg, var(--primary), var(--secondary)); border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.8rem">
                            ${initial}
                        </div>
                        <span style="font-size:0.85rem; font-weight:500">${displayName}</span>
                    </div>
                    <button onclick="AuthManager.logout()" class="btn-text" style="background:none; border:none; cursor:pointer; display:flex; align-items:center; gap:0.3rem; color:var(--text-dim)">
                        <i data-lucide="log-out" style="width:16px; height:16px"></i>
                        Çıkış
                    </button>
                </div>
            `;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
            // Kullanıcı giriş yapmamış
            navActions.innerHTML = `
                <a href="login.html" class="btn-text">Giriş Yap</a>
                <a href="login.html" class="btn-pill">Başlayın</a>
            `;
        }
    }
};

window.AuthManager = AuthManager;
