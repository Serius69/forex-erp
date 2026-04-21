// src/components/common/SkeletonLoader.tsx
import React from 'react';
import { Skeleton, Box, Card, CardContent, Grid } from '@mui/material';

// ─────────────────────────────────────────────────────────────────────────────
// KPI row skeleton — 4 cards in a row
// ─────────────────────────────────────────────────────────────────────────────

export function KPIRowSkeleton({ count = 4 }: { count?: number }) {
  return (
    <Grid container spacing={2}>
      {Array.from({ length: count }).map((_, i) => (
        <Grid item xs={12} sm={6} md={3} key={i}>
          <Card elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
            <CardContent>
              <Skeleton variant="text" width="60%" height={16} sx={{ mb: 1 }} />
              <Skeleton variant="text" width="80%" height={36} sx={{ mb: 0.5 }} />
              <Skeleton variant="text" width="40%" height={14} />
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart skeleton
// ─────────────────────────────────────────────────────────────────────────────

export function ChartSkeleton({ height = 300 }: { height?: number }) {
  return (
    <Box sx={{ p: 2 }}>
      <Skeleton variant="text" width="40%" height={24} sx={{ mb: 2 }} />
      <Skeleton variant="rectangular" width="100%" height={height} sx={{ borderRadius: 1 }} />
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Table skeleton
// ─────────────────────────────────────────────────────────────────────────────

export function TableSkeleton({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <Box sx={{ p: 1 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', gap: 2, mb: 1 }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} variant="text" width={`${100 / cols}%`} height={20} />
        ))}
      </Box>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, row) => (
        <Box key={row} sx={{ display: 'flex', gap: 2, mb: 0.5 }}>
          {Array.from({ length: cols }).map((_, col) => (
            <Skeleton
              key={col}
              variant="text"
              width={`${100 / cols}%`}
              height={18}
              sx={{ opacity: 1 - row * 0.1 }}
            />
          ))}
        </Box>
      ))}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Card skeleton (generic)
// ─────────────────────────────────────────────────────────────────────────────

export function CardSkeleton({ height = 200 }: { height?: number }) {
  return (
    <Card elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
      <CardContent>
        <Skeleton variant="text" width="50%" height={22} sx={{ mb: 1.5 }} />
        <Skeleton variant="rectangular" width="100%" height={height} sx={{ borderRadius: 1 }} />
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard full skeleton
// ─────────────────────────────────────────────────────────────────────────────

export function DashboardSkeleton() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <KPIRowSkeleton count={4} />
      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <Card elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
            <ChartSkeleton height={280} />
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
            <CardContent>
              <Skeleton variant="text" width="60%" height={22} sx={{ mb: 2 }} />
              {Array.from({ length: 5 }).map((_, i) => (
                <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1.5 }}>
                  <Skeleton variant="text" width="30%" height={16} />
                  <Skeleton variant="text" width="20%" height={16} />
                  <Skeleton variant="text" width="20%" height={16} />
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <Card elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
        <TableSkeleton rows={6} cols={6} />
      </Card>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline text skeleton (for values loading inside cards)
// ─────────────────────────────────────────────────────────────────────────────

export function ValueSkeleton({ width = 80 }: { width?: number }) {
  return <Skeleton variant="text" width={width} height={28} sx={{ display: 'inline-block' }} />;
}
