"use strict";

window.DEALCART_PRODUCTS = [
  { id: "nova-laptop", name: "NovaBook Pro 14", category: "Laptops", price: 84999, icon: "▰", tone: "violet", description: "A compact developer laptop with an OLED display and all-day battery." },
  { id: "orbit-phone", name: "Orbit X1 Phone", category: "Phones", price: 42999, icon: "▯", tone: "blue", description: "A fast 5G phone with a bright display and computational camera." },
  { id: "aura-headphones", name: "AuraSound ANC", category: "Audio", price: 9999, icon: "◉", tone: "pink", description: "Wireless over-ear headphones with adaptive noise cancellation." },
  { id: "pulse-watch", name: "PulseFit Horizon", category: "Wearables", price: 14999, icon: "⌚", tone: "green", description: "A fitness watch with GPS, AMOLED display and sleep tracking." },
  { id: "vortex-keyboard", name: "Vortex 75 Keyboard", category: "Gaming", price: 7499, icon: "⌨", tone: "orange", description: "A hot-swappable mechanical keyboard with local RGB profiles." },
  { id: "turbo-power", name: "TurboCharge 20K", category: "Accessories", price: 4999, icon: "▣", tone: "cyan", description: "A 65W USB-C power bank for laptops, tablets and phones." }
];

window.DEALCART_FLOW_DEFINITIONS = {
  account: {
    family: "account_create_delete",
    title: "DealCart account",
    acquireLabel: "Create account",
    exitLabel: "Delete account",
    acquired: "Account created. Welcome to your account.",
    exited: "Account deleted. Deletion complete.",
    hub: "Manage account settings",
    section: "Privacy and deletion controls"
  },
  subscription: {
    family: "subscribe_cancel",
    title: "DealCart VIP subscription",
    acquireLabel: "Subscribe",
    exitLabel: "Cancel subscription",
    acquired: "Subscription active. Membership active.",
    exited: "Subscription cancelled. Membership cancelled.",
    hub: "Manage subscription",
    section: "Billing and cancellation options"
  },
  newsletter: {
    family: "newsletter_subscribe_unsubscribe",
    title: "DealCart newsletter",
    acquireLabel: "Join newsletter",
    exitLabel: "Unsubscribe",
    acquired: "Subscribed successfully. Thanks for signing up.",
    exited: "Unsubscribed. You will no longer receive the newsletter.",
    hub: "Manage email preferences",
    section: "Newsletter settings"
  },
  consent: {
    family: "consent_grant_withdraw",
    title: "Personalisation consent",
    acquireLabel: "Accept consent",
    exitLabel: "Withdraw consent",
    acquired: "Consent accepted. Preferences saved.",
    exited: "Consent withdrawn. Preferences saved.",
    hub: "Manage privacy preferences",
    section: "Consent controls"
  },
  notifications: {
    family: "notifications_enable_disable",
    title: "Deal alerts",
    acquireLabel: "Enable notifications",
    exitLabel: "Disable notifications",
    acquired: "Notifications enabled. Notifications are on.",
    exited: "Notifications disabled. Notifications are off.",
    hub: "Manage notification settings",
    section: "Notification controls"
  },
  integration: {
    family: "integration_connect_disconnect",
    title: "Calendar integration",
    acquireLabel: "Connect integration",
    exitLabel: "Disconnect integration",
    acquired: "Integration connected. Successfully connected.",
    exited: "Integration disconnected. Access revoked.",
    hub: "Manage integrations",
    section: "Connected application controls"
  },
  "payment-method": {
    family: "payment_method_add_remove",
    title: "Mock payment method",
    acquireLabel: "Add payment method",
    exitLabel: "Remove payment method",
    acquired: "Payment method added. Card added.",
    exited: "Payment method removed. Card removed.",
    hub: "Manage payment methods",
    section: "Saved payment controls"
  },
  loyalty: {
    family: "loyalty_join_leave",
    title: "DealCart rewards",
    acquireLabel: "Join rewards",
    exitLabel: "Leave rewards",
    acquired: "Welcome to the rewards programme. Membership active.",
    exited: "You left the program. Membership ended.",
    hub: "Manage rewards membership",
    section: "Rewards membership controls"
  },
  "data-sharing": {
    family: "data_share_revoke",
    title: "Shopping data sharing",
    acquireLabel: "Enable data sharing",
    exitLabel: "Revoke data sharing",
    acquired: "Data sharing enabled. Permission granted.",
    exited: "Data sharing disabled. Permission revoked.",
    hub: "Manage data sharing",
    section: "Data permission controls"
  },
  "purchase-return": {
    family: "purchase_return",
    title: "Synthetic product order",
    acquireLabel: "Buy now",
    exitLabel: "Start return",
    acquired: "Order confirmed. Purchase complete.",
    exited: "Return requested. Return started.",
    hub: "Manage orders and returns",
    section: "Return controls"
  }
};
