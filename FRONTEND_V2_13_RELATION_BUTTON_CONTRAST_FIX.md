# Frontend v2.13 — Required Relation Button Contrast Fix

## Problem
The `Apply relation` button inside the Required Relation card could render as white text on a white background.

Two CSS rules were competing:
- `.primary-button.compact` supplied white text for the primary action.
- `.selected-required-relation .correction-tools button` had higher specificity and changed the background to white without changing the inherited text color.

## Fix
The Required Relation card now defines explicit primary and disabled states:
- enabled primary relation action: dark background, white text;
- disabled actions: light neutral background, muted gray text, no opacity-based contrast loss;
- secondary `Clear relation` stays white with dark text.

The rule is shared by single-element and bulk definition relation controls.
