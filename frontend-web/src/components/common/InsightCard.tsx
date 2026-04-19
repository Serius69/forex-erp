import React, { memo } from 'react';
import { Box, Card, CardContent, Typography, Skeleton } from '@mui/material';
import { TrendingUp, TrendingDown, Warning, Info, AutoAwesome } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';

export interface Insight {
  text: string;
  type: 'positive' | 'warning' | 'negative' | 'neutral';
  icon?: React.ReactNode;
}

interface InsightCardProps {
  insights: Insight[];
  loading?: boolean;
  title?: string;
}

const TYPE_MAP: Record<Insight['type'], { color: string; bg: string; border: string; icon: React.ReactNode }> = {
  positive: {
    color:  TOKENS.green,
    bg:     alpha(TOKENS.green, 0.08),
    border: alpha(TOKENS.green, 0.18),
    icon:   <TrendingUp sx={{ fontSize: 15 }} />,
  },
  warning: {
    color:  TOKENS.amber,
    bg:     alpha(TOKENS.amber, 0.08),
    border: alpha(TOKENS.amber, 0.18),
    icon:   <Warning sx={{ fontSize: 15 }} />,
  },
  negative: {
    color:  TOKENS.red,
    bg:     alpha(TOKENS.red, 0.08),
    border: alpha(TOKENS.red, 0.18),
    icon:   <TrendingDown sx={{ fontSize: 15 }} />,
  },
  neutral: {
    color:  TOKENS.blue,
    bg:     alpha(TOKENS.blue, 0.08),
    border: alpha(TOKENS.blue, 0.18),
    icon:   <Info sx={{ fontSize: 15 }} />,
  },
};

const InsightCard: React.FC<InsightCardProps> = memo(({
  insights, loading = false, title = 'Insights automáticos',
}) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <AutoAwesome sx={{ fontSize: 18, color: TOKENS.blue }} />
        <Typography variant="h6" fontWeight={700}>{title}</Typography>
      </Box>

      {loading ? (
        Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} height={40} sx={{ mb: 0.75, borderRadius: 2 }} />
        ))
      ) : insights.length === 0 ? (
        <Box sx={{ py: 2.5, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            Sin insights disponibles aún
          </Typography>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {insights.map((ins, i) => {
            const meta = TYPE_MAP[ins.type];
            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.06, ease: 'easeOut' }}
              >
                <Box sx={{
                  display: 'flex', alignItems: 'flex-start', gap: 1,
                  px: 1.5, py: 1, borderRadius: 2,
                  bgcolor: meta.bg,
                  border: `1px solid ${meta.border}`,
                }}>
                  <Box sx={{ color: meta.color, mt: 0.1, flexShrink: 0 }}>
                    {ins.icon ?? meta.icon}
                  </Box>
                  <Typography variant="body2" sx={{ color: meta.color, fontWeight: 500, lineHeight: 1.45 }}>
                    {ins.text}
                  </Typography>
                </Box>
              </motion.div>
            );
          })}
        </Box>
      )}
    </CardContent>
  </Card>
));

InsightCard.displayName = 'InsightCard';
export default InsightCard;
