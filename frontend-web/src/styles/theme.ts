import { createTheme, alpha } from '@mui/material/styles';

// ── Design tokens ─────────────────────────────────────────────────────────────
// Additional semantic tokens for status and premium accents
export const TOKENS_EXTRA = {
  // Premium gradients
  gradBlue:    'linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)',
  gradGreen:   'linear-gradient(135deg, #10B981 0%, #059669 100%)',
  gradAmber:   'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)',
  gradRed:     'linear-gradient(135deg, #EF4444 0%, #DC2626 100%)',
  // Glass surface
  glass:       'rgba(255,255,255,0.72)',
  glassBorder: 'rgba(255,255,255,0.5)',
};

export const TOKENS = {
  // Brand
  navy:    '#0F172A',
  navyMid: '#1E293B',
  navyLight:'#334155',

  // Accent
  blue:    '#2563EB',
  blueMid: '#3B82F6',
  blueLight:'#DBEAFE',

  // Semantic
  green:   '#10B981',
  greenBg: '#D1FAE5',
  red:     '#EF4444',
  redBg:   '#FEE2E2',
  amber:   '#F59E0B',
  amberBg: '#FEF3C7',

  // Neutrals
  bg:      '#F1F5F9',
  surface: '#FFFFFF',
  border:  '#E2E8F0',
  muted:   '#94A3B8',
  text:    '#0F172A',
  textSub: '#64748B',
};

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main:         TOKENS.blue,
      light:        TOKENS.blueMid,
      dark:         '#1D4ED8',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main:         TOKENS.navyMid,
      light:        TOKENS.navyLight,
      dark:         TOKENS.navy,
      contrastText: '#FFFFFF',
    },
    success: {
      main:         TOKENS.green,
      light:        '#34D399',
      dark:         '#059669',
      contrastText: '#FFFFFF',
    },
    warning: {
      main:         TOKENS.amber,
      light:        '#FCD34D',
      dark:         '#D97706',
      contrastText: '#FFFFFF',
    },
    error: {
      main:         TOKENS.red,
      light:        '#F87171',
      dark:         '#DC2626',
      contrastText: '#FFFFFF',
    },
    background: {
      default: TOKENS.bg,
      paper:   TOKENS.surface,
    },
    text: {
      primary:   TOKENS.text,
      secondary: TOKENS.textSub,
      disabled:  TOKENS.muted,
    },
    divider: TOKENS.border,
  },

  typography: {
    fontFamily: [
      'Inter',
      '-apple-system',
      'BlinkMacSystemFont',
      '"Segoe UI"',
      'Roboto',
      'sans-serif',
    ].join(','),
    h1: { fontSize: '2rem',    fontWeight: 800, letterSpacing: '-0.02em', lineHeight: 1.2 },
    h2: { fontSize: '1.75rem', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.25 },
    h3: { fontSize: '1.5rem',  fontWeight: 700, letterSpacing: '-0.01em', lineHeight: 1.3 },
    h4: { fontSize: '1.25rem', fontWeight: 700, letterSpacing: '-0.01em', lineHeight: 1.35 },
    h5: { fontSize: '1.1rem',  fontWeight: 700, lineHeight: 1.4 },
    h6: { fontSize: '1rem',    fontWeight: 600, lineHeight: 1.4 },
    subtitle1: { fontSize: '0.9375rem', fontWeight: 600, lineHeight: 1.5 },
    subtitle2: { fontSize: '0.875rem',  fontWeight: 600, lineHeight: 1.5 },
    body1: { fontSize: '0.9375rem', lineHeight: 1.6 },
    body2: { fontSize: '0.875rem',  lineHeight: 1.5 },
    caption: { fontSize: '0.75rem', lineHeight: 1.4, letterSpacing: '0.01em' },
    overline: { fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' },
    button: { fontWeight: 600, letterSpacing: '0.01em' },
  },

  shape: { borderRadius: 10 },

  shadows: [
    'none',
    '0 1px 2px rgba(15,23,42,0.06)',
    '0 1px 4px rgba(15,23,42,0.08)',
    '0 2px 8px rgba(15,23,42,0.08)',
    '0 4px 12px rgba(15,23,42,0.08)',
    '0 6px 16px rgba(15,23,42,0.08)',
    '0 8px 20px rgba(15,23,42,0.10)',
    '0 10px 24px rgba(15,23,42,0.10)',
    '0 12px 28px rgba(15,23,42,0.12)',
    '0 16px 32px rgba(15,23,42,0.12)',
    '0 20px 40px rgba(15,23,42,0.14)',
    '0 24px 48px rgba(15,23,42,0.14)',
    '0 28px 56px rgba(15,23,42,0.16)',
    '0 32px 64px rgba(15,23,42,0.16)',
    '0 36px 72px rgba(15,23,42,0.18)',
    '0 40px 80px rgba(15,23,42,0.18)',
    '0 44px 88px rgba(15,23,42,0.20)',
    '0 48px 96px rgba(15,23,42,0.20)',
    '0 52px 104px rgba(15,23,42,0.22)',
    '0 56px 112px rgba(15,23,42,0.22)',
    '0 60px 120px rgba(15,23,42,0.24)',
    '0 64px 128px rgba(15,23,42,0.24)',
    '0 68px 136px rgba(15,23,42,0.26)',
    '0 72px 144px rgba(15,23,42,0.26)',
    '0 76px 152px rgba(15,23,42,0.28)',
  ] as any,

  components: {
    // ── Button ───────────────────────────────────────────────────────────────
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          textTransform: 'none',
          borderRadius: 8,
          fontWeight: 600,
          fontSize: '0.9375rem',
          padding: '8px 18px',
          transition: 'all 0.15s ease',
          '&:active': { transform: 'scale(0.98)' },
        },
        sizeSmall: { fontSize: '0.8125rem', padding: '5px 12px', borderRadius: 6 },
        sizeLarge: { fontSize: '1rem', padding: '12px 24px', borderRadius: 10 },
        contained: {
          boxShadow: 'none',
          '&:hover': { boxShadow: '0 4px 12px rgba(37,99,235,0.3)', filter: 'brightness(1.05)' },
        },
        containedError: {
          '&:hover': { boxShadow: '0 4px 12px rgba(239,68,68,0.3)' },
        },
        containedSuccess: {
          '&:hover': { boxShadow: '0 4px 12px rgba(16,185,129,0.3)' },
        },
        outlined: {
          borderWidth: '1.5px',
          '&:hover': { borderWidth: '1.5px', backgroundColor: alpha(TOKENS.blue, 0.04) },
        },
        text: {
          '&:hover': { backgroundColor: alpha(TOKENS.blue, 0.06) },
        },
      },
    },

    // ── Card ─────────────────────────────────────────────────────────────────
    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          borderRadius: 14,
          border: `1px solid ${TOKENS.border}`,
          boxShadow: '0 1px 3px rgba(15,23,42,0.05)',
          transition: 'box-shadow 0.2s ease, transform 0.2s ease',
          '&:hover': {
            boxShadow: '0 4px 16px rgba(15,23,42,0.08)',
          },
        },
      },
    },

    // ── CardContent ──────────────────────────────────────────────────────────
    MuiCardContent: {
      styleOverrides: {
        root: {
          padding: '20px',
          '&:last-child': { paddingBottom: '20px' },
        },
      },
    },

    // ── TextField ────────────────────────────────────────────────────────────
    MuiTextField: {
      defaultProps: { variant: 'outlined', size: 'medium' },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          backgroundColor: TOKENS.surface,
          transition: 'box-shadow 0.15s ease',
          '&:hover .MuiOutlinedInput-notchedOutline': {
            borderColor: TOKENS.blue,
          },
          '&.Mui-focused': {
            boxShadow: `0 0 0 3px ${alpha(TOKENS.blue, 0.12)}`,
          },
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
            borderColor: TOKENS.blue,
            borderWidth: '1.5px',
          },
          '&.Mui-error': {
            boxShadow: `0 0 0 3px ${alpha(TOKENS.red, 0.10)}`,
          },
        },
        notchedOutline: {
          borderColor: TOKENS.border,
          transition: 'border-color 0.15s ease',
        },
        input: {
          fontWeight: 500,
        },
      },
    },

    // ── Select ───────────────────────────────────────────────────────────────
    MuiSelect: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },

    // ── Chip ─────────────────────────────────────────────────────────────────
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 600,
          fontSize: '0.75rem',
          borderRadius: 6,
          height: 24,
        },
        colorSuccess: {
          backgroundColor: TOKENS.greenBg,
          color: '#065F46',
        },
        colorError: {
          backgroundColor: TOKENS.redBg,
          color: '#991B1B',
        },
        colorWarning: {
          backgroundColor: TOKENS.amberBg,
          color: '#92400E',
        },
        colorPrimary: {
          backgroundColor: TOKENS.blueLight,
          color: '#1E40AF',
        },
      },
    },

    // ── Paper ────────────────────────────────────────────────────────────────
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: `1px solid ${TOKENS.border}`,
        },
        elevation0: { border: `1px solid ${TOKENS.border}` },
      },
    },

    // ── Table ────────────────────────────────────────────────────────────────
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-head': {
            backgroundColor: TOKENS.bg,
            color: TOKENS.textSub,
            fontWeight: 700,
            fontSize: '0.6875rem',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            borderBottom: `1px solid ${TOKENS.border}`,
            padding: '10px 16px',
          },
        },
      },
    },
    MuiTableBody: {
      styleOverrides: {
        root: {
          '& .MuiTableRow-root': {
            transition: 'background-color 0.1s ease',
            '&:hover': { backgroundColor: alpha(TOKENS.blue, 0.025) },
            '&:last-child td': { borderBottom: 'none' },
          },
          '& .MuiTableCell-body': {
            borderColor: TOKENS.border,
            padding: '12px 16px',
            fontSize: '0.875rem',
          },
        },
      },
    },

    // ── Tabs ─────────────────────────────────────────────────────────────────
    MuiTabs: {
      styleOverrides: {
        root: {
          borderBottom: `1px solid ${TOKENS.border}`,
          minHeight: 44,
        },
        indicator: {
          height: 2,
          borderRadius: '2px 2px 0 0',
          backgroundColor: TOKENS.blue,
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 600,
          fontSize: '0.875rem',
          minHeight: 44,
          padding: '8px 16px',
          color: TOKENS.textSub,
          '&.Mui-selected': { color: TOKENS.blue },
          '&:hover': { color: TOKENS.text, backgroundColor: alpha(TOKENS.blue, 0.04) },
        },
      },
    },

    // ── Tooltip ──────────────────────────────────────────────────────────────
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: TOKENS.navy,
          fontSize: '0.75rem',
          fontWeight: 500,
          borderRadius: 6,
          padding: '6px 10px',
        },
        arrow: { color: TOKENS.navy },
      },
    },

    // ── Alert ────────────────────────────────────────────────────────────────
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          border: '1px solid',
          fontWeight: 500,
          fontSize: '0.875rem',
        },
        standardSuccess: { borderColor: '#A7F3D0', backgroundColor: TOKENS.greenBg, color: '#065F46' },
        standardError:   { borderColor: '#FECACA', backgroundColor: TOKENS.redBg,   color: '#991B1B' },
        standardWarning: { borderColor: '#FDE68A', backgroundColor: TOKENS.amberBg, color: '#92400E' },
        standardInfo:    { borderColor: TOKENS.blueLight, backgroundColor: '#EFF6FF', color: '#1E40AF' },
      },
    },

    // ── Dialog ───────────────────────────────────────────────────────────────
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 16,
          boxShadow: '0 24px 48px rgba(15,23,42,0.18)',
          border: `1px solid ${TOKENS.border}`,
        },
      },
    },
    MuiDialogTitle: {
      styleOverrides: {
        root: {
          padding: '20px 24px 12px',
          fontWeight: 700,
          fontSize: '1.0625rem',
          color: TOKENS.text,
        },
      },
    },
    MuiDialogContent: {
      styleOverrides: {
        root: { padding: '12px 24px' },
      },
    },
    MuiDialogActions: {
      styleOverrides: {
        root: { padding: '16px 24px 20px', gap: 8 },
      },
    },

    // ── List ─────────────────────────────────────────────────────────────────
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          margin: '1px 8px',
          padding: '9px 12px',
          transition: 'all 0.15s ease',
          '&.Mui-selected': {
            backgroundColor: alpha(TOKENS.blue, 0.1),
            color: TOKENS.blue,
            '&:hover': { backgroundColor: alpha(TOKENS.blue, 0.14) },
            '& .MuiListItemIcon-root': { color: TOKENS.blue },
          },
          '&:hover': {
            backgroundColor: 'rgba(255,255,255,0.06)',
          },
        },
      },
    },

    // ── Skeleton ─────────────────────────────────────────────────────────────
    MuiSkeleton: {
      defaultProps: { animation: 'wave' },
      styleOverrides: {
        root: { borderRadius: 6 },
      },
    },

    // ── LinearProgress ───────────────────────────────────────────────────────
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 4, height: 5 },
        bar: { borderRadius: 4 },
      },
    },

    // ── Divider ──────────────────────────────────────────────────────────────
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: TOKENS.border },
      },
    },

    // ── Snackbar / Notistack ─────────────────────────────────────────────────
    MuiSnackbarContent: {
      styleOverrides: {
        root: { borderRadius: 10, fontWeight: 600 },
      },
    },

    // ── CssBaseline: global resets ────────────────────────────────────────────
    MuiCssBaseline: {
      styleOverrides: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

        *, *::before, *::after {
          box-sizing: border-box;
        }

        html {
          -webkit-font-smoothing: antialiased;
          -moz-osx-font-smoothing: grayscale;
          text-rendering: optimizeLegibility;
        }

        body {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          background-color: ${TOKENS.bg};
        }

        /* Slim scrollbars everywhere */
        ::-webkit-scrollbar         { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track   { background: transparent; }
        ::-webkit-scrollbar-thumb   { background: ${TOKENS.border}; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: ${TOKENS.muted}; }

        /* Text selection */
        ::selection {
          background: ${alpha(TOKENS.blue, 0.2)};
          color: ${TOKENS.text};
        }

        /* Remove number input spinners */
        input[type=number]::-webkit-inner-spin-button,
        input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; }
        input[type=number] { -moz-appearance: textfield; }

        /* Focus ring for accessibility */
        :focus-visible {
          outline: 2px solid ${TOKENS.blue};
          outline-offset: 2px;
        }

        /* Smooth transitions for theme-sensitive elements */
        .MuiCard-root,
        .MuiPaper-root,
        .MuiAppBar-root {
          transition-property: background-color, border-color, box-shadow;
          transition-duration: 0.2s;
          transition-timing-function: ease;
        }
      `,
    },
  },
});
